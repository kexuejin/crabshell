import React from 'react';
import { Box, Button, Typography } from '@mui/material';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import { useTranslation } from 'react-i18next';
import { selectFile } from '../api/tauri';

interface FileInputProps {
  value: string;
  onChange: (file: string) => void;
  disabled?: boolean;
}

const FileInput: React.FC<FileInputProps> = ({ value, onChange, disabled }) => {
  const { t } = useTranslation();

  const handleBrowse = async () => {
    const file = await selectFile();
    if (file) {
      onChange(file);
    }
  };

  const getFileName = (path: string) => path.split('/').pop() || path.split('\\').pop() || path;

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom fontWeight={600}>
        {t('fileInput.title')}
      </Typography>
      <Box
        sx={{
          border: value ? '1px solid #60A5FA' : '1px dashed #BDBDBD',
          borderRadius: 2,
          p: 2,
          textAlign: 'center',
          backgroundColor: '#FAFAFA',
          cursor: disabled ? 'not-allowed' : 'pointer',
          transition: 'all 0.15s',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 1.5,
          '&:hover': disabled
            ? {}
            : {
                borderColor: '#1976D2',
                backgroundColor: '#F8FAFC',
              },
        }}
        onClick={disabled ? undefined : handleBrowse}
      >
        {value ? (
          <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 0, gap: 0.75 }}>
            <CheckCircleIcon sx={{ color: '#1976D2', fontSize: 18 }} />
            <Typography variant="body2" sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {getFileName(value)}
            </Typography>
          </Box>
        ) : (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <FolderOpenIcon sx={{ fontSize: 18, color: '#334155' }} />
            <Typography variant="body2" color="text.secondary">
              {t('fileInput.placeholder')}
            </Typography>
          </Box>
        )}

        <Button variant="contained" size="small" disabled={disabled}>
          {t('fileInput.browse')}
        </Button>
      </Box>
    </Box>
  );
};

export default FileInput;
