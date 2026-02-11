import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

const LANGUAGE_STORAGE_KEY = 'crabshell.ui.language';

const resources = {
  en: {
    translation: {
      app: {
        title: 'CrabShell',
        outputSettings: 'Output Settings',
        advancedOptions: 'Advanced Options',
        statusError: 'Error: {{message}}',
        statusNormal: '{{progress}}% {{message}}',
        statusLoading: '{{message}}',
      },
      messages: {
        selectInputFile: 'Please select an input file',
        readyToStart: 'Ready to start',
        startingHardening: 'Starting hardening process...',
        initializingEnv: 'Preparing environment and dependencies...',
      },
      fileInput: {
        title: 'Input File',
        placeholder: 'Select APK/AAB or drag here',
        browse: 'Browse',
      },
      outputSettings: {
        outputPath: 'Output Path',
        formatSelection: 'Format Selection',
        aab: 'AAB',
        apk: 'APK',
        auto: 'Auto',
      },
      hardening: {
        title: 'Hardening',
        dexEncryption: 'DEX Encryption',
        assetEncryption: 'Asset Encryption',
        antiDebugging: 'Anti-Debugging',
        integrityChecks: 'Integrity Checks',
        stringObfuscation: 'String Obfuscation',
        keyObfuscation: 'Key Obfuscation',
      },
      signing: {
        title: 'Signing Configuration',
        debugKeystore: 'Debug Keystore',
        customKeystore: 'Custom Keystore',
        keystorePath: 'Keystore Path',
        keystorePassword: 'Keystore Password',
        keyAlias: 'Key Alias',
      },
      advanced: {
        keepClasses: 'Keep Classes',
        keepPrefixes: 'Keep Prefixes',
        keepLibraries: 'Keep Libraries',
        encryptAssets: 'Encrypt Assets',
        skipBuild: 'Skip Build',
        skipSign: 'Skip Sign',
        recommended: 'Recommended',
        libsOnly: 'Libs-Only',
        lean: 'Lean',
        loadDefault: 'Load Default',
        saveDefault: 'Save Default',
        reset: 'Reset',
        keepClassesPlaceholder: 'com.example.MainActivity',
        keepPrefixesPlaceholder: 'com.example.keep',
        keepLibrariesPlaceholder: 'mmkv, sqlite',
        encryptAssetsPlaceholder: 'assets/*.js',
        commaSeparated: 'Comma/newline separated',
        libsHelper: 'Names without lib prefix',
        assetsHelper: 'Glob patterns',
      },
      actions: {
        start: 'Start',
        cancel: 'Cancel',
      },
      language: {
        zh: '中文',
        en: 'English',
      },
    },
  },
  zh: {
    translation: {
      app: {
        title: 'CrabShell',
        outputSettings: '输出设置',
        advancedOptions: '高级选项',
        statusError: '错误：{{message}}',
        statusNormal: '{{progress}}% {{message}}',
        statusLoading: '{{message}}',
      },
      messages: {
        selectInputFile: '请选择输入文件',
        readyToStart: '准备开始',
        startingHardening: '正在启动加固流程...',
        initializingEnv: '正在准备环境与依赖...',
      },
      fileInput: {
        title: '输入文件',
        placeholder: '选择 APK/AAB 或拖拽到此处',
        browse: '浏览',
      },
      outputSettings: {
        outputPath: '输出路径',
        formatSelection: '格式选择',
        aab: 'AAB',
        apk: 'APK',
        auto: '自动',
      },
      hardening: {
        title: '加固选项',
        dexEncryption: 'DEX 加密',
        assetEncryption: '资源加密',
        antiDebugging: '反调试',
        integrityChecks: '完整性检查',
        stringObfuscation: '字符串混淆',
        keyObfuscation: '密钥混淆',
      },
      signing: {
        title: '签名配置',
        debugKeystore: '调试密钥库',
        customKeystore: '自定义密钥库',
        keystorePath: '密钥库路径',
        keystorePassword: '密钥库密码',
        keyAlias: '密钥别名',
      },
      advanced: {
        keepClasses: '保留类名',
        keepPrefixes: '保留包前缀',
        keepLibraries: '保留库',
        encryptAssets: '加密资源',
        skipBuild: '跳过构建',
        skipSign: '跳过签名',
        recommended: '推荐',
        libsOnly: '仅库配置',
        lean: '轻量调试',
        loadDefault: '加载默认',
        saveDefault: '保存默认',
        reset: '重置',
        keepClassesPlaceholder: 'com.example.MainActivity',
        keepPrefixesPlaceholder: 'com.example.keep',
        keepLibrariesPlaceholder: 'mmkv, sqlite',
        encryptAssetsPlaceholder: 'assets/*.js',
        commaSeparated: '支持逗号/换行分隔',
        libsHelper: '无需 lib 前缀',
        assetsHelper: '支持 glob 模式',
      },
      actions: {
        start: '开始',
        cancel: '取消',
      },
      language: {
        zh: '中文',
        en: 'English',
      },
    },
  },
};

const savedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY);

i18n.use(initReactI18next).init({
  resources,
  lng: savedLanguage || 'zh',
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false,
  },
});

export { LANGUAGE_STORAGE_KEY };
export default i18n;
