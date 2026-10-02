# WebUI development

The React app lives here. FastAPI serves its production bundle from
`src/codex_token_report/static/webui`, so normal Python/desktop usage requires no
Node process. Built assets are committed and included in the Python package.

Use Node.js 20 or newer and npm:

```powershell
cd frontend
npm ci
npm test
npm run build
```

Rebuild after editing the frontend. Start the existing Python service at
`http://127.0.0.1:8765`, then use `npm run dev` for React hot reload at
`http://127.0.0.1:5173`. Vite proxies `/api` to that Python service.

- `src/App.jsx`: navigation, route registration, shared application layout.
- `src/pages`: feature pages and their components.
- `src/pages/SettingsPage.jsx`: log directory and language preferences, with embedded model pricing.
- `src/components`: shared tables, charts, pagination, and date controls.
- `src/context/DashboardContext.jsx`: URL filters, scan/refresh actions, account state.
- `src/lib/api.js`: HTTP methods and localized API failures.
- `src/lib/range.js`: API query serialization, including precise reset boundaries.
- `src/lib/format.js`: locale-aware numbers, USD amounts, dates, and quota labels.
- `src/lib/i18n.js`: browser-language detection and translation/interpolation.
- `src/lib/systemMessages.js`: translations of application-owned backend messages.
- `src/test`: React behavior tests run with Vitest and Testing Library.

The Settings page offers Follow browser, Chinese, English, and Japanese. The browser
preference is saved in localStorage and switches immediately without reloading
or clearing the current filters and drafts. Follow browser is the default: it
selects the first supported language in `navigator.languages`, falling back to
`navigator.language`, then English. Supported languages are `zh`, `en`, and
`ja`; regional tags such as `zh-CN`, `zh-TW`, `en-GB`, and `ja-JP` match their base language.
Chinese uses Simplified Chinese messages. Chinese source keys supply their native
wording; English-keyed messages have a Chinese catalog in `src/lib/zhMessages.js`.
Components register language catalogs with `addMessages` and render
messages through `t(key, parameters)`. User titles and external names are kept
as data. API date/time values stay ISO; displayed values use the browser-selected
language and the configured report timezone.

To add a page, add a React component and route metadata in `App.jsx`, consume
filters through `useDashboard`, and fetch data with a query key that includes
its filters/account scope. TanStack Query handles caching, cancellation, and
refreshes. Price/scan mutations invalidate affected reports; saved quota
history stays isolated by account and pricing basis.

The log directory is persisted by `PUT /api/settings` in the local database.
Saving switches the scanner and account quota source, clears the former live
quota cache, and scans the selected directory while preserving saved history.
The old `/pricing` link redirects to `/settings` and keeps its query filters.
