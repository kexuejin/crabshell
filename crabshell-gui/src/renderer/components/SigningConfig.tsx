import React from 'react';
import { Box, Radio, RadioGroup, FormControlLabel, FormControl, TextField, Typography, IconButton } from '@mui/material';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff';
import VisibilityIcon from '@mui/icons-material/Visibility';
import { useTranslation } from 'react-i18next';
import { selectKeystore } from '../api/tauri';

interface SigningConfigProps {
  config: {
    useDebug: boolean;
    keystore?: string;
    password?: string;
    alias?: string;
  };
  onChange: (config: any) => void;
  disabled?: boolean;
}

const SigningConfig: React.FC<SigningConfigProps> = ({ config, onChange, disabled }) => {
  const { t } = useTranslation();
  const [showPassword, setShowPassword] = React.useState(false);

  const handleBrowseKeystore = async () => {
    const file = await selectKeystore();
    if (file) {
      onChange({ ...config, keystore: file });
    }
  };

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom fontWeight={600} color="primary">
        {t('signing.title')}
      </Typography>

      <FormControl component="fieldset" fullWidth>
        <RadioGroup value={config.useDebug ? 'debug' : 'custom'} onChange={(e) => onChange({ ...config, useDebug: e.target.value === 'debug' })}>
          <FormControlLabel value="debug" control={<Radio disabled={disabled} />} label={t('signing.debugKeystore')} />
          <FormControlLabel value="custom" control={<Radio disabled={disabled} />} label={t('signing.customKeystore')} />
        </RadioGroup>
      </FormControl>

      {!config.useDebug && (
        <Box sx={{ mt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box>
            <Typography variant="caption" color="text.secondary" gutterBottom display="block">
              {t('signing.keystorePath')}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <TextField
                fullWidth
                size="small"
                value={config.keystore || ''}
                onChange={(e) => onChange({ ...config, keystore: e.target.value })}
                disabled={disabled}
                placeholder="debug.keystore"
              />
              <IconButton onClick={handleBrowseKeystore} disabled={disabled} size="small" color="primary">
                <FolderOpenIcon />
              </IconButton>
            </Box>
          </Box>

          <Box>
            <Typography variant="caption" color="text.secondary" gutterBottom display="block">
              {t('signing.keystorePassword')}
            </Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <TextField
                fullWidth
                size="small"
                type={showPassword ? 'text' : 'password'}
                value={config.password || ''}
                onChange={(e) => onChange({ ...config, password: e.target.value })}
                disabled={disabled}
                placeholder="••••••••"
              />
              <IconButton onClick={() => setShowPassword(!showPassword)} size="small">
                {showPassword ? <VisibilityOffIcon /> : <VisibilityIcon />}
              </IconButton>
            </Box>
          </Box>

          <Box>
            <Typography variant="caption" color="text.secondary" gutterBottom display="block">
              {t('signing.keyAlias')}
            </Typography>
            <TextField
              fullWidth
              size="small"
              value={config.alias || ''}
              onChange={(e) => onChange({ ...config, alias: e.target.value })}
              disabled={disabled}
              placeholder="androiddebugkey"
            />
          </Box>
        </Box>
      )}
    </Box>
  );
};

export default SigningConfig;
