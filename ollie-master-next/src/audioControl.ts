export type AudioResult = {
  status: 'concluido' | 'sem_alteracao' | 'bloqueado' | 'erro' | 'parcial' | 'indeterminado' | 'ocupado';
  codigo: string;
  [key: string]: unknown;
};

// Only audio commands use this queue. A slow helper must not invert mode/volume gestures.
export function createAudioQueue(execute: (parametro: string) => Promise<string>) {
  let tail: Promise<unknown> = Promise.resolve();
  return (parametro: string): Promise<AudioResult> => {
    const result = tail.then(async () => {
      const value = JSON.parse(await execute(parametro));
      if (!value || typeof value.codigo !== 'string' || !['concluido', 'sem_alteracao', 'bloqueado', 'erro', 'parcial', 'indeterminado', 'ocupado'].includes(value.status)) {
        throw new Error('Resultado de áudio inválido.');
      }
      return value as AudioResult;
    });
    tail = result.catch(() => {});
    return result;
  };
}
