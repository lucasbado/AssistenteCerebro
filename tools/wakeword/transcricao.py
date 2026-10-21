"""Transcricao de comandos em memoria; sem rede, servidor ou execucao de acoes."""
import json
from pathlib import Path
import queue
import re
import threading

MODEL_NAME = 'faster-whisper-small'
MODEL_REPO = 'Systran/faster-whisper-small'
MODEL_REVISION = '536b0662742c02347bc0e980a01041f333bce120'
HOTWORDS = 'WhatsApp, HBO Max, Prime Video, Valorant, YouTube, Spotify'


def clean_text(text):
    # So remove a chamada conhecida. Nunca acrescenta verbos ou remove negacoes.
    text = re.sub(r'^(?:(?:ei|hey)[,\s]+)?(?:ollie|olly|oli)\b[\s,.:!?-]*', '', str(text).strip(), flags=re.I).strip()
    # STT pode omitir a preposicao em "abre Valorant PC". Mantem verbo, nome e
    # destino falados; apenas restaura a ligacao gramatical do pedido explicito.
    match = re.fullmatch(r'((?:pode )?(?:abre|abra|abrir|inicie|inicia)\s+.+?)\s+(pc|computador|celular|telefone)([.!?]*)', text, re.I)
    if match and not re.search(r'\b(?:no|pelo|pro|para o|ou|e)\s*$', match[1], re.I):
        text = f'{match[1]} no {match[2]}{match[3]}'
    return text


class LocalTranscriber:
    def __init__(self, folder):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(str(folder), device='cpu', compute_type='int8',
                                  cpu_threads=4, local_files_only=True)

    def __call__(self, pcm):
        import numpy as np
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float32) / 32768
        if not samples.size:
            return ''
        segments, _ = self.model.transcribe(samples, language='pt', beam_size=5,
            condition_on_previous_text=False, vad_filter=True,
            hotwords=HOTWORDS, max_new_tokens=96,
            vad_parameters={'threshold': .35, 'speech_pad_ms': 300, 'min_speech_duration_ms': 80})
        return clean_text(' '.join(segment.text for segment in segments))


def load_transcriber(work):
    settings = Path(work) / 'desktop-speech.json'
    if not settings.exists():
        return None  # Instalacoes antigas continuam com Vosk ate prepararem o novo modelo.
    config = json.loads(settings.read_text(encoding='utf-8'))
    if config.get('engine') != 'faster-whisper':
        raise ValueError('Reconhecedor local desconhecido. Prepare novamente a transcricao do PC.')
    folder = Path(work) / 'modelos' / MODEL_NAME
    if not (folder / 'model.bin').is_file():
        raise ValueError('Modelo de transcricao ausente. Execute preparar_transcricao.py primeiro.')
    return LocalTranscriber(folder)


class TranscriptionJobs:
    """Uma thread de inferencia. Cancelamento nao bloqueia ACKs do microfone."""
    def __init__(self, decode):
        self.decode = decode
        self.pending = queue.Queue(maxsize=1)
        self.results = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, revision, pcm):
        # So a ultima captura que ainda nao iniciou merece processamento.
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        self.pending.put_nowait((revision, pcm))

    def _run(self):
        while True:
            revision, pcm = self.pending.get()
            try:
                self.results.put((revision, self.decode(pcm), False))
            except Exception:
                self.results.put((revision, '', True))

    def poll(self):
        while True:
            try:
                yield self.results.get_nowait()
            except queue.Empty:
                return
