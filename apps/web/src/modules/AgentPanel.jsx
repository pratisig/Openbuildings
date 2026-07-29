import { useEffect, useRef, useState } from 'react';
import api from '../lib/api';
import { layersContext } from '../lib/layers';

/**
 * Panneau « Agent » — dialogue en langage naturel.
 * L'agent appelle les modules de la plateforme et renvoie des couches
 * directement affichables sur la carte.
 */
export default function AgentPanel({ map, layers, onLayer, notify }) {
  const [available, setAvailable] = useState(null);
  const [tools, setTools] = useState([]);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    api
      .agentTools()
      .then((d) => {
        setTools(d.tools);
        setAvailable(d.llm.enabled);
      })
      .catch(() => setAvailable(false));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function send() {
    const question = input.trim();
    if (!question || busy) return;
    const next = [...messages, { role: 'user', content: question }];
    setMessages(next);
    setInput('');
    setBusy(true);

    try {
      const response = await api.agentChat({
        messages: next.map((m) => ({ role: m.role, content: m.content })),
        map_context: layersContext(layers, map),
      });

      (response.layers || []).forEach((layer) => {
        onLayer({ name: layer.name, data: layer.data, source: 'Agent' });
      });

      (response.actions || []).forEach((action) => {
        if (action.action === 'fly_to' && map) {
          map.flyTo({ center: [action.longitude, action.latitude], zoom: action.zoom || 12 });
        }
      });

      setMessages([
        ...next,
        { role: 'assistant', content: response.reply, tools: response.tool_calls || [] },
      ]);
    } catch (e) {
      notify(e.message, 'error');
      setMessages([...next, { role: 'assistant', content: `Erreur : ${e.message}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  if (available === false) {
    return (
      <div className="panel">
        <div className="notice">
          <b>Agent désactivé</b>
          <p>
            Définissez <code>PRATISIG_LLM_ENABLED=true</code> et <code>PRATISIG_LLM_API_KEY</code>
            côté serveur pour l'activer. Tous les autres modules restent utilisables.
          </p>
        </div>
        <p className="hint">Outils que l'agent saurait piloter :</p>
        <ul className="tool-list">
          {tools.map((t) => (
            <li key={t.name}>
              <code>{t.name}</code>
              <span>{t.description.split('.')[0]}.</span>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="panel chat">
      <div className="chat-messages">
        {!messages.length && (
          <div className="chat-empty">
            <p>Posez une question cartographique. Exemples :</p>
            <ul>
              <li onClick={() => setInput('Montre les pharmacies dans un rayon de 1 km autour du centre de Dakar')}>
                Pharmacies autour du centre de Dakar
              </li>
              <li onClick={() => setInput('Charge les bâtiments du Sénégal autour de Thiès')}>
                Bâtiments autour de Thiès
              </li>
              <li onClick={() => setInput('Calcule un itinéraire de Dakar à Saint-Louis en voiture')}>
                Itinéraire Dakar → Saint-Louis
              </li>
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role} ${m.error ? 'error' : ''}`}>
            <div className="msg-content">{m.content}</div>
            {m.tools?.length > 0 && (
              <div className="msg-tools">
                {m.tools.map((t, j) => (
                  <span key={j} className="tool-badge">{t.tool}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="msg assistant"><div className="msg-content">Analyse en cours…</div></div>}
        <div ref={endRef} />
      </div>
      <div className="chat-input">
        <textarea
          rows={2}
          value={input}
          placeholder="Votre question…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
        />
        <button className="primary" disabled={busy || !input.trim()} onClick={send}>
          Envoyer
        </button>
      </div>
    </div>
  );
}
