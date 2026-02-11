import React from 'react';
import { Box, Checkbox, FormControlLabel, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';

interface HardeningOptionsProps {
  options: {
    dexEncryption: boolean;
    assetEncryption: boolean;
    antiDebugging: boolean;
    integrityChecks: boolean;
    stringObfuscation: boolean;
    keyObfuscation: boolean;
  };
  onChange: (options: any) => void;
  disabled?: boolean;
}

const HardeningOptions: React.FC<HardeningOptionsProps> = ({ options, onChange, disabled }) => {
  const { t } = useTranslation();

  const handleChange = (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...options, [key]: event.target.checked });
  };

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom fontWeight={600} color="primary" sx={{ mb: 0.5 }}>
        {t('hardening.title')}
      </Typography>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.25 }}>
        <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={options.dexEncryption} onChange={handleChange('dexEncryption')} disabled={disabled} />} label={t('hardening.dexEncryption')} />
        <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={options.assetEncryption} onChange={handleChange('assetEncryption')} disabled={disabled} />} label={t('hardening.assetEncryption')} />
        <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={options.antiDebugging} onChange={handleChange('antiDebugging')} disabled={disabled} />} label={t('hardening.antiDebugging')} />
        <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={options.integrityChecks} onChange={handleChange('integrityChecks')} disabled={disabled} />} label={t('hardening.integrityChecks')} />
        <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={options.stringObfuscation} onChange={handleChange('stringObfuscation')} disabled={disabled} />} label={t('hardening.stringObfuscation')} />
        <FormControlLabel sx={{ m: 0 }} control={<Checkbox size="small" checked={options.keyObfuscation} onChange={handleChange('keyObfuscation')} disabled={disabled} />} label={t('hardening.keyObfuscation')} />
      </Box>
    </Box>
  );
};

export default HardeningOptions;
