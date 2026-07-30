import { useEffect, useState } from 'react';
import api from '../lib/api';
import { IconCheck, IconChevron, IconExternal } from '../components/Icons';

/**
 * Panneau « Comptes & clés ».
 *
 * Auparavant, activer l'imagerie satellite ou l'assistant imposait d'éditer un
 * fichier `.env` puis de redémarrer le serveur — hors de portée d'un
 * utilisateur non technique, et invisible depuis l'interface.
 *
 * Ici, chaque service expose sa procédure d'inscription, ses champs et un
 * bouton de test. Les secrets ne reviennent jamais en clair du serveur :
 * l'affichage montre un masque du type `sk-p…cdef`.
 */
export default function CredentialsPanel({ notify, onChange }) {
  const [providers, setProviders] = useState([]);
  const [persistence, setPersistence] = useState(null);
  const [open, setOpen] = useState(null);
  const [drafts, setDrafts] = useState({});
  const [busy, setBusy] = useState(null);

  async function load() {
    try {
      const data = await api.credentials();
      setProviders(data.providers);
      setPersistence(data.persistence);
    } catch (e) {
      notify(e.message, 'error');
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function setField(providerId, key, value) {
    setDrafts((prev) => ({ ...prev, [providerId]: { ...prev[providerId], [key]: value } }));
  }

  async function save(provider) {
    const values = drafts[provider.id] || {};
    const missing = provider.fields
      .filter((f) => f.required && !values[f.key] && !provider.values[f.key])
      .map((f) => f.label);
    if (missing.length) {
      return notify(`Champs manquants : ${missing.join(', ')}`, 'warn');
    }

    setBusy(provider.id);
    try {
      const payload = { ...values };
      // Un champ laissé vide conserve la valeur déjà enregistrée
      provider.fields.forEach((f) => {
        if (!payload[f.key] && f.default) payload[f.key] = f.default;
      });
      const result = await api.saveCredentials(provider.id, {
        provider: provider.id,
        values: payload,
        persist: !!values.__persist,
      });
      notify(result.message, result.status.active ? 'ok' : 'warn');
      setDrafts((prev) => ({ ...prev, [provider.id]: {} }));
      await load();
      onChange?.();
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(null);
    }
  }

  async function test(provider) {
    setBusy(provider.id);
    try {
      const result = await api.testCredentials(provider.id);
      notify(result.detail, result.ok ? 'ok' : 'error');
      await load();
      onChange?.();
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(null);
    }
  }

  async function remove(provider) {
    setBusy(provider.id);
    try {
      await api.deleteCredentials(provider.id);
      notify(`${provider.label} supprimé`, 'ok');
      await load();
      onChange?.();
    } catch (e) {
      notify(e.message, 'error');
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel">
      <p className="hint">
        La plateforme fonctionne sans aucune de ces clés. Elles débloquent des
        modules supplémentaires — renseignez-les seulement si vous en avez besoin.
      </p>

      {providers.map((provider) => {
        const isOpen = open === provider.id;
        const draft = drafts[provider.id] || {};
        return (
          <div key={provider.id} className="cred-card">
            <div
              className="cred-head"
              onClick={() => setOpen(isOpen ? null : provider.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && setOpen(isOpen ? null : provider.id)}
            >
              <span className={`status-dot ${provider.status.active ? 'ok' : 'degraded'}`} />
              <div className="cred-title">
                <b>{provider.label}</b>
                <span>{provider.unlocks_label}</span>
              </div>
              <span className={`badge ${provider.status.active ? 'ok' : ''}`}>
                {provider.status.active ? 'actif' : provider.status.configured ? 'erreur' : 'inactif'}
              </span>
              <IconChevron style={{ transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform 150ms' }} />
            </div>

            {isOpen && (
              <div className="cred-body">
                <p className="hint">{provider.description}</p>

                {provider.free && <div className="notice-ok">{provider.free_note}</div>}
                {!provider.free && <div className="notice-warning">{provider.free_note}</div>}

                <div>
                  <div className="section-title">Comment obtenir la clé</div>
                  <ol className="cred-steps">
                    {provider.steps.map((step, i) => <li key={i}>{step}</li>)}
                  </ol>
                </div>

                <div className="cred-links">
                  <a href={provider.signup_url} target="_blank" rel="noreferrer">
                    Créer un compte <IconExternal />
                  </a>
                  <a href={provider.docs_url} target="_blank" rel="noreferrer">
                    Documentation <IconExternal />
                  </a>
                </div>

                <hr />

                {provider.fields.map((field) => (
                  <label key={field.key} className="field">
                    <span>
                      {field.label}
                      {field.required && <span style={{ color: 'var(--danger)' }}> *</span>}
                    </span>

                    {field.type === 'select' ? (
                      <select
                        value={draft[field.key] ?? provider.values[field.key] ?? field.default ?? ''}
                        onChange={(e) => setField(provider.id, field.key, e.target.value)}
                      >
                        {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : field.type === 'textarea' ? (
                      <textarea
                        rows={5}
                        placeholder={provider.values[field.key] || field.placeholder}
                        value={draft[field.key] ?? ''}
                        onChange={(e) => setField(provider.id, field.key, e.target.value)}
                      />
                    ) : (
                      <input
                        type={field.type === 'password' ? 'password' : 'text'}
                        placeholder={provider.values[field.key] || field.placeholder}
                        value={draft[field.key] ?? ''}
                        onChange={(e) => setField(provider.id, field.key, e.target.value)}
                      />
                    )}

                    {provider.values[field.key] && !draft[field.key] && (
                      <span style={{ fontSize: 10.5, color: 'var(--text-mute)' }}>
                        Enregistré : <code>{provider.values[field.key]}</code> — laisser vide pour conserver
                      </span>
                    )}
                  </label>
                ))}

                <label className="cred-persist">
                  <input
                    type="checkbox"
                    checked={!!draft.__persist}
                    onChange={(e) => setField(provider.id, '__persist', e.target.checked)}
                  />
                  <span>
                    Conserver après redémarrage du serveur.
                    <br />
                    <span style={{ color: 'var(--warn)' }}>
                      Écrit la clé en clair dans un fichier local — à éviter sur un poste partagé.
                    </span>
                  </span>
                </label>

                <div className="row">
                  <button className="primary" disabled={busy === provider.id} onClick={() => save(provider)}>
                    {busy === provider.id ? 'Enregistrement…' : 'Enregistrer'}
                  </button>
                  <button disabled={busy === provider.id} onClick={() => test(provider)}>
                    <IconCheck /> Tester
                  </button>
                </div>

                {provider.status.configured && (
                  <button className="danger" disabled={busy === provider.id} onClick={() => remove(provider)}>
                    Supprimer les identifiants
                  </button>
                )}

                <p className="hint">
                  État : {provider.status.detail}
                </p>
              </div>
            )}
          </div>
        );
      })}

      {persistence && (
        <p className="hint disclaimer">
          Les clés enregistrées vivent en mémoire par défaut et disparaissent à
          l'arrêt du serveur. Si vous cochez la conservation, elles sont écrites
          dans <code>{persistence.path}</code>, exclu du dépôt Git.
        </p>
      )}
    </div>
  );
}
