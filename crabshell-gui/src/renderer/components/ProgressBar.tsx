import React from 'react';
import { Box, LinearProgress, Typography } from '@mui/material';

interface ProgressBarProps {
    progress: number;
    message: string;
    stage: 'init' | 'building' | 'packing' | 'signing' | 'done' | 'error';
}

const ProgressBar: React.FC<ProgressBarProps> = ({ progress, message, stage }) => {
    const getColor = () => {
        if (stage === 'error') return 'error';
        if (stage === 'done') return 'success';
        return 'primary';
    };

    return (
        <Box>
            <Typography variant="subtitle2" gutterBottom fontWeight={600}>
                Progress
            </Typography>

            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
                <Box sx={{ flex: 1 }}>
                    <LinearProgress
                        variant="determinate"
                        value={progress}
                        color={getColor()}
                        sx={{ height: 8, borderRadius: 4 }}
                    />
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 45 }}>
                    {progress}%
                </Typography>
            </Box>

            <Typography variant="body2" color="text.secondary">
                {message}
            </Typography>
        </Box>
    );
};

export default ProgressBar;
