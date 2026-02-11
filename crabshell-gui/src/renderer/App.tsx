import React, { useMemo, useState } from 'react';
import {
  Button,
  Box,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  LinearProgress,
  Paper,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import { useTranslation } from 'react-i18next';
import FileInput from './components/FileInput';
import OutputSettings from './components/OutputSettings';
import SigningConfig from './components/SigningConfig';
import ActionButtons from './components/ActionButtons';
import LanguageSwitcher from './components/LanguageSwitcher';
import type { HardeningConfig, HardeningProgress } from '../shared/types';
import { cancelHardening, onProgress, startHardening } from './api/tauri';

const ADVANCED_STORAGE_KEY = 'crabshell.advanced.defaults.v1';

const sectionCardSx = {
  p: 1.5,
  borderRadius: 2,
  border: '1px solid #E2E8F0',
  boxShadow: 'none',
  backgroundColor: '#FFFFFF',
};

const ADVANCED_PRESETS = {
  recommended: {
    keepClasses: [],
    keepPrefixes: [],
    keepLibs: ['mmkv'],
    encryptAssets: [],
    skipBuild: false,
    skipSign: false,
  },
  libsOnly: {
    keepClasses: [],
    keepPrefixes: [],
    keepLibs: ['mmkv', 'sqlite', 'c++_shared'],
    encryptAssets: [],
    skipBuild: false,
    skipSign: false,
  },
  leanDebug: {
    keepClasses: [],
    keepPrefixes: [],
    keepLibs: ['mmkv'],
    encryptAssets: [],
    skipBuild: true,
    skipSign: true,
  },
};

const App: React.FC = () => {
  const { t } = useTranslation();

  const [config, setConfig] = useState<HardeningConfig>({
    inputFile: '',
    outputFile: 'protected.aab',
    outputFormat: 'auto',
    advanced: {
      keepClasses: [],
      keepPrefixes: [],
      keepLibs: ['mmkv'],
      encryptAssets: [],
      skipBuild: false,
      skipSign: false,
    },
    signing: {
      useDebug: true,
    },
  });

  const [progress, setProgress] = useState<HardeningProgress>({
    stage: 'init',
    progress: 0,
    message: t('messages.readyToStart'),
  });
  const [isProcessing, setIsProcessing] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const isIndeterminateProgress =
    isProcessing &&
    progress.stage === 'init' &&
    progress.progress <= 5;

  const statusText = useMemo(() => {
    if (progress.stage === 'error') {
      return t('app.statusError', { message: progress.message });
    }

    if (isIndeterminateProgress) {
      return t('app.statusLoading', { message: progress.message });
    }

    return t('app.statusNormal', { progress: progress.progress, message: progress.message });
  }, [isIndeterminateProgress, progress, t]);

  const parseList = (value: string) =>
    value
      .split(/[\n,;]/g)
      .map((item) => item.trim())
      .filter(Boolean);

  const stringifyList = (list: string[]) => list.join(', ');

  const applyAdvancedPreset = (preset: keyof typeof ADVANCED_PRESETS) => {
    setConfig({
      ...config,
      advanced: ADVANCED_PRESETS[preset],
    });
  };

  const saveAdvancedDefaults = () => {
    localStorage.setItem(ADVANCED_STORAGE_KEY, JSON.stringify(config.advanced));
  };

  const loadAdvancedDefaults = () => {
    try {
      const raw = localStorage.getItem(ADVANCED_STORAGE_KEY);
      if (!raw) {
        return;
      }

      const parsed = JSON.parse(raw) as HardeningConfig['advanced'];
      setConfig((current) => ({
        ...current,
        advanced: {
          keepClasses: parsed.keepClasses ?? [],
          keepPrefixes: parsed.keepPrefixes ?? [],
          keepLibs: parsed.keepLibs ?? [],
          encryptAssets: parsed.encryptAssets ?? [],
          skipBuild: Boolean(parsed.skipBuild),
          skipSign: Boolean(parsed.skipSign),
        },
      }));
    } catch {
      localStorage.removeItem(ADVANCED_STORAGE_KEY);
    }
  };

  const clearAdvancedOptions = () => {
    setConfig({
      ...config,
      advanced: {
        keepClasses: [],
        keepPrefixes: [],
        keepLibs: [],
        encryptAssets: [],
        skipBuild: false,
        skipSign: false,
      },
    });
  };

  const handleStart = async () => {
    if (!config.inputFile) {
      alert(t('messages.selectInputFile'));
      return;
    }

    setIsProcessing(true);
    setProgress({
      stage: 'init',
      progress: 1,
      message: t('messages.initializingEnv'),
    });

    try {
      await startHardening(config);
    } catch (error) {
      const message = String(error);
      setProgress({
        stage: 'error',
        progress: 0,
        message,
      });
      setIsProcessing(false);
    }
  };

  const handleCancel = async () => {
    await cancelHardening();
    setIsProcessing(false);
  };

  React.useEffect(() => {
    loadAdvancedDefaults();

    let unlistenProgress: (() => void) | undefined;

    onProgress((data) => {
      setProgress(data);
      if (data.stage === 'done' || data.stage === 'error') {
        setIsProcessing(false);
      }
    }).then((cleanup) => {
      unlistenProgress = cleanup;
    });

    return () => {
      if (unlistenProgress) {
        unlistenProgress();
      }
    };
  }, []);

  return (
    <Box
      sx={{
        backgroundColor: '#F1F5F9',
        pt: 1,
        pb: 0.5,
      }}
    >
      <Container
        maxWidth="md"
        sx={{
          px: { xs: 1, sm: 1.5 },
        }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#0F172A' }}>
            {t('app.title')}
          </Typography>
          <LanguageSwitcher />
        </Box>

        <Paper
          elevation={0}
          sx={{
            ...sectionCardSx,
            p: 1,
            mb: 1,
            border: '1px dashed #CBD5E1',
            backgroundColor: '#F8FAFC',
          }}
        >
          <FileInput value={config.inputFile} onChange={(file) => setConfig({ ...config, inputFile: file })} disabled={isProcessing} />
        </Paper>

        <Paper elevation={0} sx={{ ...sectionCardSx, mb: 1 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700 }}>
            {t('app.outputSettings')}
          </Typography>
          <OutputSettings
            outputFile={config.outputFile}
            outputFormat={config.outputFormat}
            onOutputFileChange={(file) => setConfig({ ...config, outputFile: file })}
            onFormatChange={(format) => setConfig({ ...config, outputFormat: format })}
            disabled={isProcessing}
          />
        </Paper>

        <Paper elevation={0} sx={{ ...sectionCardSx, mb: 1 }}>
          <SigningConfig config={config.signing} onChange={(signing) => setConfig({ ...config, signing })} disabled={isProcessing} />
        </Paper>

        <Paper
          elevation={0}
          sx={{
            ...sectionCardSx,
            py: 0.9,
            mb: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            cursor: 'pointer',
          }}
          onClick={() => setAdvancedOpen(true)}
        >
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {t('app.advancedOptions')}
          </Typography>
          <IconButton size="small" disabled={isProcessing}>
            <KeyboardArrowDownIcon fontSize="small" />
          </IconButton>
        </Paper>

        <Dialog
          open={advancedOpen}
          onClose={() => setAdvancedOpen(false)}
          fullWidth
          maxWidth="md"
        >
          <DialogTitle sx={{ pb: 1 }}>{t('app.advancedOptions')}</DialogTitle>
          <DialogContent sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 1.25 }}>
            <Box sx={{ gridColumn: '1 / -1', display: 'flex', flexWrap: 'wrap', gap: 0.75 }}>
              <Button size="small" variant="outlined" disabled={isProcessing} onClick={() => applyAdvancedPreset('recommended')}>
                {t('advanced.recommended')}
              </Button>
              <Button size="small" variant="outlined" disabled={isProcessing} onClick={() => applyAdvancedPreset('libsOnly')}>
                {t('advanced.libsOnly')}
              </Button>
              <Button size="small" variant="outlined" disabled={isProcessing} onClick={() => applyAdvancedPreset('leanDebug')}>
                {t('advanced.lean')}
              </Button>
              <Button size="small" variant="text" disabled={isProcessing} onClick={loadAdvancedDefaults}>
                {t('advanced.loadDefault')}
              </Button>
              <Button size="small" variant="text" disabled={isProcessing} onClick={saveAdvancedDefaults}>
                {t('advanced.saveDefault')}
              </Button>
              <Button size="small" color="inherit" variant="text" disabled={isProcessing} onClick={clearAdvancedOptions}>
                {t('advanced.reset')}
              </Button>
            </Box>

            <TextField
              size="small"
              label={t('advanced.keepClasses')}
              value={stringifyList(config.advanced.keepClasses)}
              onChange={(event) =>
                setConfig({
                  ...config,
                  advanced: {
                    ...config.advanced,
                    keepClasses: parseList(event.target.value),
                  },
                })
              }
              placeholder={t('advanced.keepClassesPlaceholder')}
              disabled={isProcessing}
              helperText={t('advanced.commaSeparated')}
            />

            <TextField
              size="small"
              label={t('advanced.keepPrefixes')}
              value={stringifyList(config.advanced.keepPrefixes)}
              onChange={(event) =>
                setConfig({
                  ...config,
                  advanced: {
                    ...config.advanced,
                    keepPrefixes: parseList(event.target.value),
                  },
                })
              }
              placeholder={t('advanced.keepPrefixesPlaceholder')}
              disabled={isProcessing}
              helperText={t('advanced.commaSeparated')}
            />

            <TextField
              size="small"
              label={t('advanced.keepLibraries')}
              value={stringifyList(config.advanced.keepLibs)}
              onChange={(event) =>
                setConfig({
                  ...config,
                  advanced: {
                    ...config.advanced,
                    keepLibs: parseList(event.target.value),
                  },
                })
              }
              placeholder={t('advanced.keepLibrariesPlaceholder')}
              disabled={isProcessing}
              helperText={t('advanced.libsHelper')}
            />

            <TextField
              size="small"
              label={t('advanced.encryptAssets')}
              value={stringifyList(config.advanced.encryptAssets)}
              onChange={(event) =>
                setConfig({
                  ...config,
                  advanced: {
                    ...config.advanced,
                    encryptAssets: parseList(event.target.value),
                  },
                })
              }
              placeholder={t('advanced.encryptAssetsPlaceholder')}
              disabled={isProcessing}
              helperText={t('advanced.assetsHelper')}
            />

            <FormControlLabel
              control={
                <Switch
                  checked={config.advanced.skipBuild}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      advanced: {
                        ...config.advanced,
                        skipBuild: event.target.checked,
                      },
                    })
                  }
                  disabled={isProcessing}
                  size="small"
                />
              }
              label={t('advanced.skipBuild')}
            />

            <FormControlLabel
              control={
                <Switch
                  checked={config.advanced.skipSign}
                  onChange={(event) =>
                    setConfig({
                      ...config,
                      advanced: {
                        ...config.advanced,
                        skipSign: event.target.checked,
                      },
                    })
                  }
                  disabled={isProcessing}
                  size="small"
                />
              }
              label={t('advanced.skipSign')}
            />
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button size="small" onClick={() => setAdvancedOpen(false)}>
              {t('actions.cancel')}
            </Button>
          </DialogActions>
        </Dialog>

        <Paper
          elevation={0}
          sx={{
            ...sectionCardSx,
            p: 1,
            mb: 0.5,
          }}
        >
          <Typography variant="caption" sx={{ color: '#0F172A', fontWeight: 600, mb: 0.5, display: 'block' }}>
            {statusText}
          </Typography>
          <LinearProgress
            variant={isIndeterminateProgress ? 'indeterminate' : 'determinate'}
            value={isIndeterminateProgress ? undefined : progress.progress}
            sx={{
              height: 8,
              borderRadius: 999,
              backgroundColor: '#E2E8F0',
              mb: 0.75,
              '& .MuiLinearProgress-bar': {
                backgroundColor: '#0284C7',
                borderRadius: 999,
              },
            }}
          />
          <ActionButtons onStart={handleStart} onCancel={handleCancel} isProcessing={isProcessing} canStart={Boolean(config.inputFile)} />
        </Paper>
      </Container>
    </Box>
  );
};

export default App;
