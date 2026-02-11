export interface HardeningConfig {
    inputFile: string;
    outputFile: string;
    outputFormat: 'auto' | 'apk' | 'aab';
    options: {
        dexEncryption: boolean;
        assetEncryption: boolean;
        antiDebugging: boolean;
        integrityChecks: boolean;
        stringObfuscation: boolean;
        keyObfuscation: boolean;
    };
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
    progress: number; // 0-100
    message: string;
}

export interface LogEntry {
    timestamp: string;
    level: 'info' | 'warning' | 'error';
    message: string;
}
