import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import './i18n'; // Import i18n configuration

const theme = createTheme({
    palette: {
        primary: {
            main: '#1976D2',
        },
        secondary: {
            main: '#757575',
        },
        success: {
            main: '#4CAF50',
        },
        error: {
            main: '#F44336',
        },
        warning: {
            main: '#FF9800',
        },
        background: {
            default: '#FAFAFA',
            paper: '#FFFFFF',
        },
    },
    typography: {
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    },
    shape: {
        borderRadius: 8,
    },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <ThemeProvider theme={theme}>
            <CssBaseline />
            <App />
        </ThemeProvider>
    </React.StrictMode>
);
