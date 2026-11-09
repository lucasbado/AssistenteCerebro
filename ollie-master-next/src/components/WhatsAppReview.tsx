import { useState } from 'react';
import { openUrl } from '@tauri-apps/plugin-opener';
import { whatsappDraftUrl, type WhatsAppDraft } from '../whatsappDraft';

export default function WhatsAppReview({ drafts, remove }: {
  drafts: WhatsAppDraft[];
  remove: (id: string) => void;
}) {
  if (!drafts.length) return null;
  return <section className="agenda-panel" aria-label="Rascunhos do WhatsApp">
    <h2>Rascunhos do WhatsApp</h2>
    <p>Confira o número e o texto. O botão abre a conversa com a mensagem preenchida. Envie pelo WhatsApp.</p>
    <div className="message-review-list">
      {drafts.map(draft => <DraftReview key={draft.id} draft={draft} remove={remove} />)}
    </div>
  </section>;
}

function DraftReview({ draft, remove }: { draft: WhatsAppDraft; remove: (id: string) => void }) {
  const [opening, setOpening] = useState(false);
  const [feedback, setFeedback] = useState('');

  async function open() {
    setOpening(true);
    setFeedback('');
    try {
      await openUrl(whatsappDraftUrl(draft));
      setFeedback('Pedi para abrir a conversa. Confira o destinatário no WhatsApp.');
    } catch {
      setFeedback('Não consegui abrir a conversa. Você pode copiar o texto e abrir o WhatsApp.');
    } finally {
      setOpening(false);
    }
  }

  return <article className="agenda-card message-review-card">
    <h3>+{draft.numero}</h3>
    <blockquote>{draft.texto}</blockquote>
    <div className="agenda-actions">
      <button className="button button-primary" disabled={opening} onClick={() => void open()}>Abrir no WhatsApp</button>
      <button className="button" disabled={opening} onClick={() => remove(draft.id)}>Retirar da revisão</button>
    </div>
    <p role="status">{feedback}</p>
  </article>;
}
