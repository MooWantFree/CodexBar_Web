import {createContext, useCallback, useContext, useMemo, useState} from 'react';
import {useSearchParams} from 'react-router-dom';
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query';
import {apiGet, apiPost, apiPut} from '../lib/api';
import {readRange, rangeQuery} from '../lib/range';

const DashboardContext = createContext(null);

export function offlineQuota(snapshot, error) {
  if (!error) return snapshot;
  return {
    ...snapshot, status: 'error', message: error.message, windows: [], plan_type: null,
    history_mode: snapshot?.reset_history_scope ? 'offline' : 'unavailable',
    history_label: snapshot?.history_mode === 'offline' || snapshot?.history_directory_verified === false
      ? snapshot.history_label || '上次保存的账号' : '上次保存的账号',
    history_fetched_at: snapshot?.history_fetched_at || snapshot?.fetched_at,
  };
}

export function DashboardProvider({config, children}) {
  const [activeConfig, setActiveConfig] = useState(config);
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const range = useMemo(() => readRange(params, activeConfig), [params, activeConfig]);
  const applyConfig = useCallback(next => {
    setActiveConfig(current => ({...current, ...next}));
    Object.assign(document.body.dataset, next);
  }, []);
  const queryString = useCallback(extra => rangeQuery(range, extra), [range]);
  const setRange = useCallback(patch => {
    const next = {...range, ...patch};
    const nextParams = new URLSearchParams(rangeQuery(next));
    // Keep the selected session on reload and browser back/forward navigation.
    for (const key of ['session', 'session_scope']) if (params.has(key)) nextParams.set(key, params.get(key));
    setParams(nextParams, {replace: true});
  }, [range, params, setParams]);
  const quotaQuery = useQuery({queryKey: ['quota'], queryFn: ({signal}) => apiGet('/api/quota', {signal}), staleTime: Infinity});
  const quotaMutation = useMutation({
    onMutate: () => client.cancelQueries({predicate: query => query.queryKey[0] === 'quota' || String(query.queryKey[0]).startsWith('quota-value')}),
    mutationFn: () => apiPost('/api/quota/refresh'),
    onSuccess: async snapshot => {
      client.setQueryData(['quota'], snapshot);
      await client.invalidateQueries({predicate: query => query.queryKey[0] !== 'quota'});
    },
  });
  const scanMutation = useMutation({
    onMutate: () => client.cancelQueries({predicate: query => query.queryKey[0] !== 'quota'}),
    mutationFn: () => apiPost('/api/scan'),
    onSuccess: () => client.invalidateQueries({predicate: query => query.queryKey[0] !== 'quota'}),
  });
  const settingsMutation = useMutation({
    mutationFn: values => apiPut('/api/settings', values),
    onMutate: () => client.cancelQueries(),
    onError: () => { void client.invalidateQueries(); },
    onSuccess: async result => {
      await client.cancelQueries();
      quotaMutation.reset();
      scanMutation.reset();
      // A new log root may belong to another account. Discard its former live
      // snapshot and saved-value cache before requesting the new source.
      client.removeQueries({predicate: query => String(query.queryKey[0]).startsWith('quota-value')});
      client.setQueryData(['quota'], null);
      client.setQueryData(['settings'], result);
      applyConfig({...result.ui_config, codexHome: result.codex_home});
      void client.invalidateQueries({queryKey: ['quota']});
      try {
        await scanMutation.mutateAsync();
        applyConfig(await apiGet('/api/ui-config'));
      } catch {
        // Saving the directory succeeded. A scan failure remains visible via
        // scanError without reverting the saved path.
      }
    },
  });
  const quotaError = quotaMutation.error || quotaQuery.error;
  const quota = useMemo(() => offlineQuota(quotaQuery.data, quotaError), [quotaQuery.data, quotaError]);
  const refreshUsage = useCallback(() => client.invalidateQueries({predicate: query => query.queryKey[0] !== 'quota'}), [client]);
  const value = {
    ...activeConfig, range, setRange, queryString, rangeKey: queryString(),
    quota, quotaLoading: quotaQuery.isPending || quotaQuery.isFetching,
    quotaError,
    quotaRefreshing: quotaMutation.isPending,
    refreshQuota: quotaMutation.mutateAsync,
    scan: scanMutation.mutateAsync, scanning: scanMutation.isPending || settingsMutation.isPending, scanError: scanMutation.error,
    saveSettings: settingsMutation.mutateAsync, settingsSaving: settingsMutation.isPending,
    refreshUsage,
  };
  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard() {
  const value = useContext(DashboardContext);
  if (!value) throw new Error('DashboardProvider is required');
  return value;
}
