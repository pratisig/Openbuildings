import { useEffect, useState } from 'react';
import api from '../lib/api';

/**
 * Panneau « À propos » — répond directement au problème initial :
 * « j'ai oublié l'objectif de certains projets ».
 * Affiche le catalogue des modules et la traçabilité de chaque dépôt d'origine.
 */
export default function AboutPanel() {
  const [catalog, setCatalog] = useState(null);
  const [migration, setMigration] = useState(null);
  const [health, setHealth] = useState(null);
  const [view, setView] = useState('modules');

  useEffect(() => {
    api.catalog().then(setCatalog).catch(() => {});
    api.migration().then(setMigration).catch(() => {});
    api.health().then(setHealth).catch(() => {});
  }, []);

  return (
    <div className="panel">
      <div className="tabs">
        {[
          ['modules', 'Modules'],
          ['origines', 'Origines'],
          ['sante', 'Services'],
        ].map(([id, label]) => (
          <button key={id} className={view === id ? 'tab active' : 'tab'} onClick={() => setView(id)}>
            {label}
          </button>
        ))}
      </div>

      {view === 'modules' && catalog && (
        <div className="about">
          <p className="hint">{catalog.count} modules regroupés en une seule plateforme.</p>
          {catalog.groups.map((group) => (
            <div key={group.name} className="about-group">
              <h4>{group.name}</h4>
              {group.modules.map((m) => (
                <div key={m.id} className="about-item">
                  <div className="about-head">
                    <b>{m.label}</b>
                    <span className={`badge ${m.status}`}>{m.status}</span>
                  </div>
                  <p>{m.summary}</p>
                  <div className="about-origin">
                    Vient de : {m.origin.map((o) => <code key={o}>{o.split('/')[1]}</code>)}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {view === 'origines' && migration && (
        <div className="about">
          <p className="hint">
            {migration.count} dépôts d'origine : {migration.personnels} personnels,{' '}
            {migration.forks} forks, {migration.inaccessibles} inaccessibles.
          </p>
          {migration.sources.map((s) => (
            <div key={s.repo} className={`about-item origin-${s.type.split(' ')[0]}`}>
              <div className="about-head">
                <b>{s.repo.split('/')[1]}</b>
                <span className="badge">{s.type}</span>
              </div>
              <p><i>Rôle d'origine :</i> {s.role_origine}</p>
              <p><i>Devenu :</i> <code>{s.destination}</code></p>
              <p className="note">{s.note}</p>
            </div>
          ))}
        </div>
      )}

      {view === 'sante' && health && (
        <div className="about">
          <p className="hint">
            État global : <b>{health.status === 'ok' ? 'tous les services actifs' : 'mode dégradé'}</b>
          </p>
          {Object.entries(health.services).map(([name, svc]) => (
            <div key={name} className="about-item">
              <div className="about-head">
                <b>{name}</b>
                <span className={`badge ${svc.status}`}>{svc.status}</span>
              </div>
              <p>{svc.detail}</p>
              <p className="note">Alimente : {svc.powers.join(', ')}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
