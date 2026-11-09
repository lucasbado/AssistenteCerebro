export const fileCommands = new Set([
  'buscar_documentos', 'abrir_arquivo', 'listar_arquivos', 'capturar_tela',
  'criar_pasta', 'copiar_arquivo', 'mover_arquivo', 'renomear_arquivo', 'compactar_arquivo',
  'prever_organizacao', 'organizar_pasta', 'desfazer_organizacao', 'lixeira_arquivo', 'restaurar_lixeira',
]);

export function pcCommandParam(command: string, data: Record<string, unknown>): string {
  const param = String(data.url ?? data.parametro ?? data.app ?? data.query ?? data.macro ?? data.valor ?? '');
  if (command === 'volume_canal' && data.canal != null) {
    return `${data.canal},${data.valor ?? data.parametro ?? ''}`;
  }
  if (command === 'mouse_move' && (data.dx != null || data.dy != null)) {
    return `${data.dx ?? 0},${data.dy ?? 0}`;
  }
  if (command === 'mouse_click') return String(data.botao ?? param);
  if (command === 'mouse_scroll') return String(data.quantidade ?? param);
  if (command === 'buscar_documentos') return String(data.termo ?? param);
  if (command === 'listar_arquivos') return String(data.caminho ?? param);
  return param;
}

export type FileResult = { arquivo: { estado: string; itens: string[] } };
export type SystemResult = { sistema: { cpu: number; ram: number; disco: number } };

export function readFileResult(raw: string): FileResult {
  const result = JSON.parse(raw);
  const file = result?.arquivo;
  if (!file || typeof file.estado !== 'string' || !Array.isArray(file.itens) ||
      file.itens.some((item: unknown) => typeof item !== 'string')) {
    throw new Error('O executor devolveu um resultado de arquivo inválido.');
  }
  return { arquivo: { estado: file.estado, itens: file.itens } };
}

export function readSystemResult(raw: string): SystemResult {
  const system = JSON.parse(raw)?.sistema;
  if (!system || [system.cpu, system.ram, system.disco].some(value =>
    !Number.isFinite(value) || value < 0 || value > 100)) {
    throw new Error('O executor devolveu medições inválidas.');
  }
  return { sistema: { cpu: system.cpu, ram: system.ram, disco: system.disco } };
}
