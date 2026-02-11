import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { HardeningConfig, HardeningProgress, LogEntry } from '../../shared/types';

export async function selectFile(): Promise<string | null> {
  return invoke<string | null>('select_file');
}

export async function selectKeystore(): Promise<string | null> {
  return invoke<string | null>('select_keystore');
}

export async function selectOutput(defaultPath: string): Promise<string | null> {
  return invoke<string | null>('select_output', { defaultPath });
}

export async function startHardening(config: HardeningConfig): Promise<void> {
  return invoke('start_hardening', { config });
}

export async function cancelHardening(): Promise<void> {
  return invoke('cancel_hardening');
}

export async function onProgress(callback: (data: HardeningProgress) => void): Promise<() => void> {
  return listen<HardeningProgress>('hardening-progress', (event) => callback(event.payload));
}

export async function onLog(callback: (data: LogEntry) => void): Promise<() => void> {
  return listen<LogEntry>('hardening-log', (event) => callback(event.payload));
}
