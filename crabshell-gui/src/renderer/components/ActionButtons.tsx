import React from 'react';
import { Box, Button } from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import { useTranslation } from 'react-i18next';

interface ActionButtonsProps {
  onStart: () => void;
  onCancel: () => void;
  isProcessing: boolean;
  canStart: boolean;
}

const ActionButtons: React.FC<ActionButtonsProps> = ({ onStart, onCancel, isProcessing, canStart }) => {
  const { t } = useTranslation();

  return (
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1.25 }}>
      {isProcessing ? (
        <Button variant="contained" color="error" onClick={onCancel} startIcon={<StopIcon />} size="small" sx={{ borderRadius: 999, px: 2.25 }}>
          {t('actions.cancel')}
        </Button>
      ) : (
        <>
          <Button
            variant="contained"
            size="small"
            onClick={onCancel}
            sx={{
              borderRadius: 999,
              px: 2.25,
              backgroundColor: '#E2E8F0',
              color: '#334155',
              boxShadow: 'none',
              '&:hover': { backgroundColor: '#CBD5E1', boxShadow: 'none' },
            }}
          >
            {t('actions.cancel')}
          </Button>
          <Button variant="contained" color="primary" onClick={onStart} disabled={!canStart} startIcon={<PlayArrowIcon />} size="small" sx={{ borderRadius: 999, px: 2.25 }}>
            {t('actions.start')}
          </Button>
        </>
      )}
    </Box>
  );
};

export default ActionButtons;
