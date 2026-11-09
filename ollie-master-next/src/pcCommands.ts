export const fileCommands = new Set([
  'buscar_documentos', 'abrir_arquivo', 'listar_arquivos', 'capturar_tela',
  'criar_pasta', 'copiar_arquivo', 'mover_arquivo', 'renomear_arquivo', 'compactar_arquivo',
  'prever_organizacao', 'organizar_pasta', 'desfazer_organizacao', 'lixeira_arquivo', 'restaurar_lixeira',
  'criar_arquivo', 'ler_arquivo', 'acrescentar_texto',
]);
export const windowQueries = new Set(['janela_ativa', 'listar_janelas']);

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

export type FileResult = { arquivo: { estado: string; itens: string[]; texto?: string; parcial?: boolean } };
export type SystemResult = { sistema: { cpu: number; ram: number; disco: number } };
export type WindowResult = { janelas: { titulo: string; processo: string }[]; total: number };

export function readFileResult(raw: string): FileResult {
  const result = JSON.parse(raw);
  const file = result?.arquivo;
  if (!file || typeof file.estado !== 'string' || !Array.isArray(file.itens) ||
      file.itens.some((item: unknown) => typeof item !== 'string')) {
    throw new Error('O executor devolveu um resultado de arquivo inválido.');
  }
  if (file.estado === 'lido') {
    if (typeof file.texto !== 'string' || typeof file.parcial !== 'boolean') {
      throw new Error('A leitura não devolveu conteúdo válido.');
    }
    return { arquivo: { estado: file.estado, itens: file.itens, texto: file.texto, parcial: file.parcial } };
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

export function readWindowResult(raw: string, command: string): WindowResult {
  const result = JSON.parse(raw);
  const limit = command === 'janela_ativa' ? 1 : 8;
  if (!result || !Number.isInteger(result.total) || result.total < 0 || result.total > 65535 ||
      (command === 'janela_ativa' && result.total > 1) || !Array.isArray(result.janelas) ||
      result.janelas.length !== Math.min(result.total, limit)) {
    throw new Error('O executor devolveu uma observação de janelas inválida.');
  }
  const janelas = result.janelas.map((item: unknown) => {
    const window = item as WindowResult['janelas'][number] | null;
    if (!window || typeof window.titulo !== 'string' || !window.titulo ||
        typeof window.processo !== 'string' || !window.processo) {
      throw new Error('O executor devolveu uma janela inválida.');
    }
    return { titulo: window.titulo, processo: window.processo };
  });
  return { janelas, total: result.total };
}
