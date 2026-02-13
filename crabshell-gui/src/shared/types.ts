export interface HardeningConfig {
    inputFile: string;
    outputFile: string;
    outputFormat: 'auto' | 'apk' | 'aab';
    advanced: {
        keepClasses: string[];
        keepPrefixes: string[];
        keepLibs: string[];
        encryptAssets: string[];
        skipBuild: boolean;
        skipSign: boolean;
    };
    signing: {
        useDebug: boolean;
        keystore?: string;
        password?: string;
        alias?: string;
    };
}

export interface HardeningProgress {
    stage: 'init' | 'building' | 'packing' | 'signing' | 'done' | 'error';
    substage?: string;
    progress: number; // 0-100
    message: string;
}

export interface LogEntry {
    timestamp: string;
    level: 'info' | 'warning' | 'error';
    message: string;
}
