import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter} from 'react-router-dom';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {DashboardProvider} from './context/DashboardContext';
import {t} from './lib/i18n';
import App, {PageErrorBoundary} from './App';
import {AppSkeleton} from './components/UsageSkeleton';
import ServiceConnectionGuard from './components/ServiceConnectionGuard';
import './styles.css';

const root = createRoot(document.getElementById('root'));
const render = content => root.render(<React.StrictMode><ServiceConnectionGuard>{content}</ServiceConnectionGuard></React.StrictMode>);

async function bootstrap() {
  render(<AppSkeleton/>);
  const config = document.body.dataset.defaultStart ? {...document.body.dataset}
    : await fetch('/api/ui-config').then(response => {
      if (!response.ok) throw new Error(t('请求失败（{status}）', {status: response.status}));
      return response.json();
    });
  Object.assign(document.body.dataset, config);
  const client = new QueryClient({defaultOptions: {queries: {retry: false, refetchOnWindowFocus: false, staleTime: 30_000}}});
  render(<PageErrorBoundary><QueryClientProvider client={client}><BrowserRouter><DashboardProvider config={config}><App /></DashboardProvider></BrowserRouter></QueryClientProvider></PageErrorBoundary>);
}
bootstrap().catch(error => render(<section className="panel bootstrap-error" role="alert">{error.message}</section>));
