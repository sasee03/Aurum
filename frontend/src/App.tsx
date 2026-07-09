import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { AppModeProvider } from '@/context/AppModeContext';
import { AppRouter } from '@/routes';
import '@/components/aurum-assistant/aurum-assistant.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppModeProvider>
        <AppRouter />
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: '#13141e',
              color: '#f1f5f9',
              border: '1px solid #252637',
              fontSize: '13px',
              borderRadius: '10px',
            },
            success: {
              iconTheme: { primary: '#22c55e', secondary: '#13141e' },
            },
            error: {
              iconTheme: { primary: '#ef4444', secondary: '#13141e' },
            },
          }}
        />
      </AppModeProvider>
    </QueryClientProvider>
  );
}

export default App;
