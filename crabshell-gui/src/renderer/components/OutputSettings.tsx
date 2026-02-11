import React from 'react';
import { Box, TextField, Radio, RadioGroup, FormControlLabel, FormControl, Typography, IconButton } from '@mui/material';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import { useTranslation } from 'react-i18next';
import { selectOutput } from '../api/tauri';

interface OutputSettingsProps {
  outputFile: string;
  outputFormat: 'auto' | 'apk' | 'aab';
  onOutputFileChange: (file: string) => void;
  onFormatChange: (format: 'auto' | 'apk' | 'aab') => void;
  disabled?: boolean;
}

const OutputSettings: React.FC<OutputSettingsProps> = ({
  outputFile,
  outputFormat,
  onOutputFileChange,
  onFormatChange,
  disabled,
}) => {
  const { t } = useTranslation();

  const handleBrowse = async () => {
    const file = await selectOutput(outputFile);
    if (file) {
      onOutputFileChange(file);
    }
  };

  return (
    <Box>
      <Box sx={{ mb: 1.25 }}>
        <Typography variant="caption" color="text.secondary" gutterBottom display="block">
          {t('outputSettings.outputPath')}
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField
            fullWidth
            size="small"
            value={outputFile}
            onChange={(e) => onOutputFileChange(e.target.value)}
            disabled={disabled}
            placeholder="protected.aab"
          />
          <IconButton onClick={handleBrowse} disabled={disabled} color="primary" size="small">
            <FolderOpenIcon />
          </IconButton>
        </Box>
      </Box>

      <Box>
        <Typography variant="caption" color="text.secondary" gutterBottom display="block">
          {t('outputSettings.formatSelection')}
        </Typography>
        <FormControl component="fieldset" size="small">
          <RadioGroup row value={outputFormat} onChange={(e) => onFormatChange(e.target.value as 'auto' | 'apk' | 'aab')}>
            <FormControlLabel value="aab" control={<Radio size="small" disabled={disabled} />} label={t('outputSettings.aab')} />
            <FormControlLabel value="apk" control={<Radio size="small" disabled={disabled} />} label={t('outputSettings.apk')} />
            <FormControlLabel value="auto" control={<Radio size="small" disabled={disabled} />} label={t('outputSettings.auto')} />
          </RadioGroup>
        </FormControl>
      </Box>
    </Box>
  );
};

export default OutputSettings;
