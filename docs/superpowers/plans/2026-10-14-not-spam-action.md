# Acción "No es spam" — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el usuario pueda sacar una conversación de Spam desde la app: el mensaje vuelve a Recibidos en el proveedor (Gmail / Outlook / IMAP) y localmente, y queda marcado como "no basura" para que el detector no lo vuelva a marcar.

**Architecture:** Nueva variante `ThreadAction::NotSpam` en el mecanismo de acciones de hilo existente (`services/emails/thread_actions.rs`): planner puro (mensajes con `mailbox == "spam"`) + ejecutor que reutiliza `restore_from_spam` (`services/emails/spam.rs`, ya usado por "desbloquear remitente") y graba la corrección con `junk::set_feedback(.., false)` bajo el id que el mensaje tiene después del movimiento. En el frontend, una acción de store `markThreadsNotSpam` sobre `runThreadAction` (optimista + rollback + toast ya resueltos), un botón "No es spam" en la barra del hilo cuando la conversación tiene mensajes en Spam, y el botón "No es basura" del `JunkBanner` redirigido a esa acción cuando el mensaje está en Spam.

**Tech Stack:** Rust (Tauri 2, rusqlite, tokio), React + TypeScript, Zustand, vitest, i18next (en/es/fr/de).

**Spec:** No hay documento de spec aparte. La especificación es la conversación del 14/10/2026: hoy no hay forma de sacar un correo de Spam desde la app; "No es basura" solo borra la etiqueta local (`src-tauri/src/services/junk/mod.rs:293`) y el `JunkBanner` solo aparece si el detector marcó el correo (`isFlagged`). Lo que se pide: que "No es basura" saque el correo de Spam, igual que "Confirmar basura" lo mete (`report_junk_to_provider`).

## Flujo, paso a paso

1. El usuario abre una conversación desde la vista Spam (o una conversación con algún mensaje en Spam, por ejemplo desde una búsqueda).
2. La barra del hilo muestra un botón "No es spam" (icono de Recibidos). Si el detector local marcó el mensaje, el `JunkBanner` muestra además "No es basura".
3. Cualquiera de los dos llama a `useEmailStore.markThreadsNotSpam([threadRef])`.
4. El store, de forma optimista, cambia `mailbox` de `spam` a `inbox` en las filas de esas conversaciones y, si la lista visible es Spam, las quita de la lista (`leavesList('notSpam', 'spam') === true`).
5. El store llama a `api.applyThreadAction(threads, 'notSpam')`, que termina en `apply_thread_action` → `apply_to_thread` en Rust.
6. Por cada mensaje del hilo con `mailbox == "spam"`:
   - `restore_from_spam` llama a `provider.move_message(id, message_id, MoveTarget::Inbox)`. Gmail quita la etiqueta `SPAM` y pone `INBOX` (`sync/gmail.rs:2075`), Outlook mueve a `inbox`, IMAP hace MOVE (y re-keyea el id).
   - Re-archiva la fila local en `inbox` con el id nuevo (`refile_moved_row`).
   - `junk::set_feedback(db, account_id, new_id, false)` graba `user_override = 'not_junk'` y borra la etiqueta `junk`. La sobrescritura es permanente: sobrevive a re-puntuaciones del detector.
7. Si el proveedor falla (sin conexión, credenciales caducadas, permisos), el hilo se queda en Spam; el report lo lista como fallido y el store hace rollback y muestra el toast `threadActions.failed.notSpam`.
8. Una cuenta sin escritura en el proveedor (`LocalOnly`) mueve solo en local.

## Global Constraints

- Trabajar en un worktree nuevo desde `main`, rama `feature/not-spam` (no en `fix/compose-paragraph-spacing`, que es trabajo no relacionado).
- TDD obligatorio: test que falla → mínimo código → verde → commit.
- Código, identificadores, comentarios y commits en inglés; commits `type: short description` < 72 caracteres, sin trailer `Co-Authored-By` de Claude ni enlaces de sesión.
- Sin datos personales reales en tests ni commits: direcciones `@example.com`, ids sintéticos.
- i18n en los cuatro idiomas (`src/locales/{en,es,fr,de}/inbox.json`) en el mismo commit que introduce la clave.
- Frontend: Node 22 de nvm (vitest/biome/tsc fallan con el node v20 del PATH por defecto).
- No añadir dependencias. No añadir flags ni ajustes de configuración.
- Errores nunca descartados: el fallo del proveedor llega al toast + log (ya lo hace `commitThreadAction`).
- Gates por el subagente `gate-runner` (`make gates SET=commit`, y `SET=push` porque cambia comportamiento Rust) y `privacy-reviewer` (scope `staged`) antes de cada commit relevante.

## Review Focus

1. **Hilo mixto (Recibidos + Spam):** solo se mueven los mensajes en Spam; los de Recibidos/Enviados no generan llamadas al proveedor. → test de planner en Task 1.
2. **IMAP/Outlook re-keyean el mensaje al moverlo:** la marca `not_junk` tiene que quedar bajo el id nuevo, no el viejo; si no, el detector lo vuelve a marcar en el siguiente backfill. → test con `set_move_result` en Task 1.
3. **El proveedor ya no tiene el mensaje (`NotFound`):** se mueve en local igualmente (mismo criterio que `restore_from_spam`), sin error. → test con un mensaje que el fake no conoce en Task 1.
4. **Proveedor inalcanzable o que rechaza (offline, token sin `gmail.modify`):** el hilo se queda en Spam y el usuario ve el error. → test `Unreachable` en Task 1 y test de rollback en Task 2.
5. **Correo en Spam sin veredicto del detector (lo puso ahí el servidor):** el `JunkBanner` no aparece, pero el botón de la barra sí. → test del helper puro `threadMailboxState` en Task 3.

---

### Task 1: Backend — `ThreadAction::NotSpam`

**Files:**
- Modify: `src-tauri/src/services/emails/thread_actions.rs` (enum `ThreadAction` ~l.55, doc + `plan_thread_action` ~l.110-140, `verb`/`past_tense` ~l.280-300, `apply_to_thread` match ~l.330, nueva fn `not_spam_message` junto a `move_message_to_inbox` ~l.420; tests en el módulo `tests`)
- Modify: `src-tauri/src/services/emails/MODULE.md` si enumera las acciones de hilo (comprobar con Grep `MoveToInbox`)

**Interfaces:**
- Consumes: `super::spam::restore_from_spam(db: &Database, email: &Email, provider: Option<&dyn EmailProvider>) -> Result<String>` (devuelve el id nuevo); `crate::services::junk::set_feedback(db: &Arc<Database>, account_id: &str, email_id: &str, is_junk: bool) -> Result<()>`.
- Produces: variante `ThreadAction::NotSpam`, serializada como `"notSpam"` (serde `rename_all = "camelCase"`). El comando Tauri `apply_thread_action` ya la acepta sin cambios.

- [ ] **Step 1: Test del planner que falla**

En `mod tests`, debajo de `archive_takes_only_inbox_messages_and_move_to_inbox_brings_back_archived_and_foldered_ones`:

```rust
    #[test]
    fn not_spam_takes_only_the_spam_messages() {
        let thread = [
            message("in", 1, "inbox"),
            message("sent", 2, "sent"),
            message("junk1", 3, "spam"),
            message("arch", 4, "archive"),
            message("junk2", 5, "spam"),
        ];
        assert_eq!(
            plan_thread_action(ThreadAction::NotSpam, &thread),
            ids(&["junk1", "junk2"])
        );
    }
```

- [ ] **Step 2: Verlo fallar**

Run: `cd src-tauri && cargo test --no-default-features --lib thread_actions::tests::not_spam_takes_only_the_spam_messages`
Expected: FAIL de compilación: `no variant named NotSpam found for enum ThreadAction`.

- [ ] **Step 3: Variante + planner + textos de log**

En el enum, después de `MoveToInbox`:

```rust
    MoveToInbox,
    /// Take every Spam message of the conversation back to the inbox and
    /// record that it is not junk, so the detector never re-flags it.
    NotSpam,
```

En la doc de `plan_thread_action`, después de la línea de **Move to inbox**:

```rust
/// - **Not spam** brings back every message filed in Spam.
```

En el `match` de `plan_thread_action`:

```rust
        ThreadAction::MoveToInbox => ids(&|m| m.mailbox == "archive" || m.mailbox.starts_with("folder:")),
        ThreadAction::NotSpam => ids(&|m| m.mailbox == "spam"),
```

En `verb`: `ThreadAction::NotSpam => "take out of spam",`
En `past_tense`: `ThreadAction::NotSpam => "Moved out of spam",`

En `apply_to_thread`, de momento para que compile (el Step 7 lo sustituye):

```rust
            ThreadAction::NotSpam => not_spam_message(db, email, writable(access)?).await?,
```

y una implementación mínima debajo de `move_message_to_inbox`:

```rust
/// Bring one Spam message back to the inbox — the inverse of "Confirm junk" —
/// and record the user's judgement under the id the message has now (IMAP
/// and Graph re-key a moved message).
async fn not_spam_message(db: &Arc<Database>, email: &Email, provider: Option<&dyn EmailProvider>) -> Result<()> {
    super::spam::restore_from_spam(db, email, pushable(provider, email)).await?;
    Ok(())
}
```

- [ ] **Step 4: Verlo pasar**

Run: `cd src-tauri && cargo test --no-default-features --lib thread_actions::tests::not_spam_takes_only_the_spam_messages`
Expected: PASS.

- [ ] **Step 5: Tests del ejecutor que fallan**

En `mod tests`, debajo de `move_to_inbox_brings_an_archived_thread_back_through_the_provider`:

```rust
    fn junk_override(db: &Database, id: &str) -> Option<String> {
        db.get_junk_verdicts_batch(&[id.to_string()])
            .unwrap()
            .remove(id)
            .and_then(|v| v.user_override)
    }

    #[tokio::test]
    async fn not_spam_moves_the_spam_messages_to_the_inbox_and_records_not_junk() {
        let junk = message("a", 1, "spam");
        let db = test_db(&[junk.clone(), message("b", 2, "inbox")]);
        let provider = FakeEmailProvider::new("me@example.com", "Me");
        provider.add_message(junk, EmailCategory::Primary, vec![]);

        run(&db, ThreadAction::NotSpam, ProviderAccess::Ready(&provider))
            .await
            .unwrap();

        assert_eq!(row(&db, "a").unwrap().mailbox, "inbox");
        assert_eq!(
            provider.folder_ops(),
            vec![FakeFolderOp::Move {
                message_id: "a".to_string(),
                mailbox_value: "inbox".to_string()
            }]
        );
        assert_eq!(junk_override(&db, "a").as_deref(), Some("not_junk"));
        assert_eq!(junk_override(&db, "b"), None);
    }

    #[tokio::test]
    async fn not_spam_records_not_junk_under_the_id_the_provider_gave_the_message() {
        let junk = message("a", 1, "spam");
        let db = test_db(std::slice::from_ref(&junk));
        let provider = FakeEmailProvider::new("me@example.com", "Me");
        provider.add_message(junk, EmailCategory::Primary, vec![]);
        provider.set_move_result(Some(MessageRef {
            id: "a-moved".to_string(),
            thread_id: "t-1".to_string(),
        }));

        run(&db, ThreadAction::NotSpam, ProviderAccess::Ready(&provider))
            .await
            .unwrap();

        assert_eq!(row(&db, "a-moved").unwrap().mailbox, "inbox");
        assert_eq!(junk_override(&db, "a-moved").as_deref(), Some("not_junk"));
    }

    #[tokio::test]
    async fn not_spam_of_a_message_the_provider_lost_is_moved_locally() {
        // The fake provider has never seen "a": its move answers NotFound.
        let db = test_db(&[message("a", 1, "spam")]);
        let provider = FakeEmailProvider::new("me@example.com", "Me");

        run(&db, ThreadAction::NotSpam, ProviderAccess::Ready(&provider))
            .await
            .unwrap();

        assert_eq!(row(&db, "a").unwrap().mailbox, "inbox");
        assert_eq!(junk_override(&db, "a").as_deref(), Some("not_junk"));
    }

    #[tokio::test]
    async fn not_spam_with_an_unreachable_provider_leaves_the_thread_in_spam() {
        let db = test_db(&[message("a", 1, "spam")]);
        let offline = AppError::SyncError("offline".to_string());

        let err = run(&db, ThreadAction::NotSpam, ProviderAccess::Unreachable(&offline))
            .await
            .unwrap_err();

        assert!(matches!(err, AppError::SyncError(_)), "{err:?}");
        assert_eq!(row(&db, "a").unwrap().mailbox, "spam");
        assert_eq!(junk_override(&db, "a"), None);
    }

    #[tokio::test]
    async fn not_spam_on_a_local_only_account_moves_without_provider_calls() {
        let db = test_db(&[message("a", 1, "spam")]);

        run(&db, ThreadAction::NotSpam, ProviderAccess::LocalOnly)
            .await
            .unwrap();

        assert_eq!(row(&db, "a").unwrap().mailbox, "inbox");
        assert_eq!(junk_override(&db, "a").as_deref(), Some("not_junk"));
    }
```

Si `MessageRef` no está importado en `mod tests`, añadirlo al `use crate::sync::provider::{…}` del módulo de tests.

- [ ] **Step 6: Verlos fallar**

Run: `cd src-tauri && cargo test --no-default-features --lib thread_actions::tests::not_spam`
Expected: compilan; `…moves_the_spam_messages…`, `…under_the_id…`, `…provider_lost…` y `…local_only…` FALLAN en la aserción de `junk_override` (`left: None, right: Some("not_junk")`). `…unreachable…` pasa.

- [ ] **Step 7: Implementación completa**

Sustituir `not_spam_message` por:

```rust
/// Bring one Spam message back to the inbox — the inverse of "Confirm junk" —
/// and record the user's judgement under the id the message has now (IMAP
/// and Graph re-key a moved message). The move comes first: a refused move
/// leaves the message in Spam and records nothing.
async fn not_spam_message(db: &Arc<Database>, email: &Email, provider: Option<&dyn EmailProvider>) -> Result<()> {
    let new_id = super::spam::restore_from_spam(db, email, pushable(provider, email)).await?;
    crate::services::junk::set_feedback(db, &email.account_id, &new_id, false).await
}
```

- [ ] **Step 8: Verlos pasar, y el módulo entero**

Run: `cd src-tauri && cargo test --no-default-features --lib thread_actions`
Expected: todos PASS.

Run: `cd src-tauri && cargo test --no-default-features --lib spam`
Expected: PASS (no se tocó `spam.rs`, pero comparte `refile_moved_row`).

- [ ] **Step 9: MODULE.md**

Grep `MoveToInbox\|move to inbox` en `src-tauri/src/services/emails/MODULE.md`. Si enumera las acciones de hilo, añadir `NotSpam` con una línea ("take Spam messages back to the inbox and record not-junk"). Si no las enumera, no tocarlo.

- [ ] **Step 10: Gates y commit**

Subagente `gate-runner` con `SET=commit` en el worktree; corregir todo lo que reporte. `privacy-reviewer` scope `staged`.

```bash
git add src-tauri/src/services/emails/thread_actions.rs src-tauri/src/services/emails/MODULE.md
git commit -m "feat: add a not-spam thread action with provider write-back"
```

---

### Task 2: Frontend store — `markThreadsNotSpam`

**Files:**
- Modify: `src/lib/api.ts:368` (tipo `ThreadAction`)
- Modify: `src/stores/emailStore.ts` (`leavesList` ~l.267, interfaz del store ~l.544, acción junto a `moveThreadsToInbox` ~l.1227)
- Modify: `src/locales/{en,es,fr,de}/inbox.json` (`threadActions.failed.notSpam_one/_other`)
- Test: `src/stores/emailStore.threadActions.test.ts`

**Interfaces:**
- Consumes: `ThreadAction::NotSpam` serializado como `'notSpam'` (Task 1).
- Produces: `useEmailStore.getState().markThreadsNotSpam(threads: ThreadRef[]): Promise<void>`; `leavesList('notSpam', 'spam') === true`.

- [ ] **Step 1: Tests que fallan**

En `emailStore.threadActions.test.ts`, añadir a la tabla de `describe('leavesList')`:

```ts
    ['notSpam', 'spam', true],
    ['notSpam', 'inbox', false],
    ['notSpam', 'search', false],
```

Y dentro de `describe('thread action store actions', …)`:

```ts
  it('not spam moves the spam rows to the inbox and leaves the Spam list', async () => {
    vi.mocked(api.applyThreadAction).mockResolvedValue({ failed: [] });
    useEmailStore.setState({
      listScope: 'spam',
      emails: [email('s1', 't1', { mailbox: 'spam' }), email('s2', 't2', { mailbox: 'spam' })],
      totalCount: 2,
    });

    await useEmailStore.getState().markThreadsNotSpam([{ accountId: 'acc', threadId: 't1' }]);

    expect(api.applyThreadAction).toHaveBeenCalledWith([{ accountId: 'acc', threadId: 't1' }], 'notSpam');
    expect(useEmailStore.getState().emails.map((e) => e.id)).toEqual(['s2']);
  });

  it('a refused not-spam puts the conversation back in the Spam list with a toast', async () => {
    vi.mocked(api.applyThreadAction).mockResolvedValue({
      failed: [{ accountId: 'acc', threadId: 't1', code: 'sync', params: {}, message: 'offline' }],
    });
    useEmailStore.setState({
      listScope: 'spam',
      emails: [email('s1', 't1', { mailbox: 'spam' })],
      totalCount: 1,
    });

    await useEmailStore.getState().markThreadsNotSpam([{ accountId: 'acc', threadId: 't1' }]);

    expect(useEmailStore.getState().emails.map((e) => [e.id, e.mailbox])).toEqual([['s1', 'spam']]);
    expect(useToastStore.getState().toasts.at(-1)?.message).toMatch(/spam/i);
  });
```

Antes de escribirlos, comprobar en el propio fichero cómo los tests existentes fijan `listScope` y leen los toasts (`useToastStore.getState().toasts`) y copiar esa forma exacta si difiere.

- [ ] **Step 2: Verlos fallar**

Run: `npx vitest run src/stores/emailStore.threadActions.test.ts` (con Node 22 de nvm)
Expected: FAIL. `tsc` / vitest se quejan de `'notSpam'` no asignable a `ThreadAction` y de que `markThreadsNotSpam` no es una función.

- [ ] **Step 3: Implementación mínima**

`src/lib/api.ts:368`:

```ts
export type ThreadAction =
  | 'markRead'
  | 'markUnread'
  | 'star'
  | 'unstar'
  | 'archive'
  | 'moveToInbox'
  | 'notSpam'
  | 'delete';
```

`leavesList` en `emailStore.ts`:

```ts
    case 'moveToInbox':
      return list === 'archive' || list.startsWith('folder:');
    case 'notSpam':
      return list === 'spam';
```

Interfaz del store, junto a `moveThreadsToInbox`:

```ts
  /** Take the conversations' Spam messages back to the inbox, at the
   *  provider too, and record that they are not junk. */
  markThreadsNotSpam: (threads: ThreadRef[]) => Promise<void>;
```

Acción, debajo de `moveThreadsToInbox`:

```ts
  markThreadsNotSpam: (threads) =>
    runThreadAction(threads, 'notSpam', (state, keys) => ({
      ...state,
      emails: state.emails.map((e) => (keys.has(keyOf(e)) && e.mailbox === 'spam' ? { ...e, mailbox: 'inbox' } : e)),
    })),
```

i18n, dentro de `threadActions.failed`, después de `moveToInbox_other`:

- en: `"notSpam_one": "Could not move {{count}} conversation out of spam: {{detail}}",` / `"notSpam_other": "Could not move {{count}} conversations out of spam: {{detail}}",`
- es: `"notSpam_one": "No se pudo sacar de spam {{count}} conversación: {{detail}}",` / `"notSpam_other": "No se pudieron sacar de spam {{count}} conversaciones: {{detail}}",`
- fr: `"notSpam_one": "Impossible de sortir {{count}} conversation du spam : {{detail}}",` / `"notSpam_other": "Impossible de sortir {{count}} conversations du spam : {{detail}}",`
- de: `"notSpam_one": "{{count}} Unterhaltung konnte nicht aus dem Spam verschoben werden: {{detail}}",` / `"notSpam_other": "{{count}} Unterhaltungen konnten nicht aus dem Spam verschoben werden: {{detail}}",`

- [ ] **Step 4: Verlos pasar**

Run: `npx vitest run src/stores/emailStore.threadActions.test.ts`
Expected: PASS. Si hay un test de paridad de claves i18n (Grep `locales` en `src/**/*.test.ts`), ejecutarlo también.

- [ ] **Step 5: Gates y commit**

`gate-runner` `SET=frontend` (biome + tsc + vitest); `privacy-reviewer` `staged`.

```bash
git add src/lib/api.ts src/stores/emailStore.ts src/stores/emailStore.threadActions.test.ts src/locales/*/inbox.json
git commit -m "feat: add markThreadsNotSpam to the email store"
```

---

### Task 3: UI — botón "No es spam" en la barra del hilo y "No es basura" del banner

**Files:**
- Modify: `src/components/EmailView/EmailView.tsx` (`ThreadToolbarActions` ~l.1031-1085 y su uso ~l.720)
- Modify: `src/components/EmailView/JunkBanner.tsx` (props + `handleNotJunk`)
- Modify: `src/components/EmailView/ThreadEmailItem.tsx:164` (pasar `threadId` y `mailbox`)
- Modify: `src/locales/{en,es,fr,de}/inbox.json` (`emailView.notSpam`)
- Test: `src/components/EmailView/threadMailboxState.test.ts` (nuevo), `src/components/EmailView/JunkBanner.notSpam.test.tsx` (nuevo)

**Interfaces:**
- Consumes: `useEmailStore.getState().markThreadsNotSpam(threads: ThreadRef[])` (Task 2).
- Produces: `export function threadMailboxState(emails: Pick<Email, 'mailbox'>[]): { inInbox: boolean; archived: boolean; inSpam: boolean }` en `EmailView.tsx`; nuevas props de `JunkBanner`: `threadId: string`, `mailbox: string`.

- [ ] **Step 1: Test del helper puro que falla**

Crear `src/components/EmailView/threadMailboxState.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { threadMailboxState } from './EmailView';

const m = (mailbox: string) => ({ mailbox });

describe('threadMailboxState', () => {
  it.each([
    ['inbox only', [m('inbox')], { inInbox: true, archived: false, inSpam: false }],
    ['archived only', [m('archive')], { inInbox: false, archived: true, inSpam: false }],
    ['spam only, no detector verdict needed', [m('spam')], { inInbox: false, archived: false, inSpam: true }],
    ['inbox and spam', [m('inbox'), m('spam')], { inInbox: true, archived: false, inSpam: true }],
    ['sent and trash', [m('sent'), m('trash')], { inInbox: false, archived: false, inSpam: false }],
  ])('%s', (_name, emails, expected) => {
    expect(threadMailboxState(emails)).toEqual(expected);
  });
});
```

- [ ] **Step 2: Verlo fallar**

Run: `npx vitest run src/components/EmailView/threadMailboxState.test.ts`
Expected: FAIL: `threadMailboxState is not exported`.

- [ ] **Step 3: Helper + botón**

En `EmailView.tsx`, encima de `interface ThreadToolbarActionsProps`:

```ts
/** Pure: which mailbox actions a conversation offers, from where its
 *  messages are filed. A conversation in Spam offers "Not spam" whether or
 *  not the junk detector flagged it — the server may have filed it there. */
export function threadMailboxState(emails: Pick<Email, 'mailbox'>[]): {
  inInbox: boolean;
  archived: boolean;
  inSpam: boolean;
} {
  const inInbox = emails.some((e) => e.mailbox === 'inbox');
  return {
    inInbox,
    archived: !inInbox && emails.some((e) => e.mailbox === 'archive'),
    inSpam: emails.some((e) => e.mailbox === 'spam'),
  };
}
```

En `ThreadToolbarActionsProps` añadir `onNotSpam: () => void;` y en la desestructuración `onNotSpam,`. Sustituir:

```ts
  const inInbox = threadEmails.some((e) => e.mailbox === 'inbox');
  const archived = !inInbox && threadEmails.some((e) => e.mailbox === 'archive');
```

por:

```ts
  const { inInbox, archived, inSpam } = threadMailboxState(threadEmails);
```

Y debajo del bloque `{archived && (…)}`:

```tsx
      {inSpam && (
        <button onClick={onNotSpam} className={buttonClass} title={t('inbox:emailView.notSpam')}>
          <InboxIcon className="w-4 h-4" />
        </button>
      )}
```

En el uso (~l.722), junto a `onMoveToInbox`:

```tsx
              onNotSpam={() => {
                void markThreadsNotSpam([threadRefOf(latestEmail)]);
                onClose();
              }}
```

con `markThreadsNotSpam` sacado del store igual que `moveThreadsToInbox` en ese componente (Grep `moveThreadsToInbox` en `EmailView.tsx` y copiar la forma).

i18n `emailView.notSpam`, después de `moveToInbox`:
- en: `"notSpam": "Not spam — move to Inbox"`
- es: `"notSpam": "No es spam — mover a Recibidos"`
- fr: `"notSpam": "Pas un spam — déplacer vers la boîte de réception"`
- de: `"notSpam": "Kein Spam — in den Posteingang verschieben"`

- [ ] **Step 4: Verlo pasar**

Run: `npx vitest run src/components/EmailView/threadMailboxState.test.ts src/components/EmailView/EmailView.tooltips.test.tsx src/components/EmailView/EmailView.shortcuts.test.tsx`
Expected: PASS. Si `EmailView.tooltips.test.tsx` comprueba que cada botón de la barra tiene `title`, el nuevo ya lo tiene.

- [ ] **Step 5: Test del banner que falla**

Crear `src/components/EmailView/JunkBanner.notSpam.test.tsx`, copiando el montaje (mocks, `initI18n`, `createRoot` + `act`) de `JunkBanner.autoAdvance.test.tsx` líneas 1-70:

```tsx
// "Not junk" on a message filed in Spam takes the conversation out of Spam
// (the not-spam thread action); elsewhere it only records the correction.

// …mocks e imports copiados de JunkBanner.autoAdvance.test.tsx…

const notJunkButton = () =>
  Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Not junk') as HTMLButtonElement;

async function renderBanner(mailbox: string) {
  await act(async () =>
    root.render(<JunkBanner emailId="e2" accountId="a1" threadId="t2" mailbox={mailbox} />),
  );
}

describe('JunkBanner not junk', () => {
  it('in Spam it takes the conversation out of Spam', async () => {
    const markThreadsNotSpam = vi.fn(async () => undefined);
    useEmailStore.setState({ markThreadsNotSpam });
    await renderBanner('spam');

    await act(async () => notJunkButton().click());

    expect(markThreadsNotSpam).toHaveBeenCalledWith([{ accountId: 'a1', threadId: 't2' }]);
    expect(api.setJunkFeedback).not.toHaveBeenCalled();
  });

  it('outside Spam it only records the correction', async () => {
    const markThreadsNotSpam = vi.fn(async () => undefined);
    useEmailStore.setState({ markThreadsNotSpam });
    await renderBanner('inbox');

    await act(async () => notJunkButton().click());

    expect(api.setJunkFeedback).toHaveBeenCalledWith('a1', 'e2', false);
    expect(markThreadsNotSpam).not.toHaveBeenCalled();
  });
});
```

Asegurarse de que el `vi.mock('@/lib/api', …)` copiado incluye `setJunkFeedback: vi.fn(async () => undefined)`.

- [ ] **Step 6: Verlo fallar**

Run: `npx vitest run src/components/EmailView/JunkBanner.notSpam.test.tsx`
Expected: FAIL: el primer test ve `setJunkFeedback` llamado y `markThreadsNotSpam` no (y tsc se queja de las props `threadId`/`mailbox` desconocidas).

- [ ] **Step 7: Implementación en el banner**

`JunkBannerProps`:

```ts
interface JunkBannerProps {
  emailId: string;
  accountId: string;
  threadId: string;
  /** Where the message is filed: in Spam, "Not junk" also takes it out. */
  mailbox: string;
}
```

Firma: `export function JunkBanner({ emailId, accountId, threadId, mailbox }: JunkBannerProps)`. Sustituir `handleNotJunk` por:

```ts
  // In Spam, "Not junk" is the not-spam thread action: it moves the
  // conversation back to the inbox at the provider and records the
  // correction (the store reports a refusal with a toast and rolls back).
  // Elsewhere there is nothing to move, so only the correction is recorded.
  const handleNotJunk = useCallback(async () => {
    if (mailbox === 'spam') {
      await useEmailStore.getState().markThreadsNotSpam([{ accountId, threadId }]);
      return;
    }
    try {
      await setFeedback(accountId, emailId, false);
    } catch (err) {
      const message = `${t('inbox:junk.notJunkFailed')}: ${errorText(err)}`;
      addLog('error', 'system', message);
      addToast({ message, sticky: true });
    }
  }, [accountId, emailId, threadId, mailbox, setFeedback, addLog, addToast, t]);
```

Importar `useEmailStore` desde `@/stores/emailStore` si el fichero aún no lo hace.

`ThreadEmailItem.tsx:164`:

```tsx
            <JunkBanner emailId={email.id} accountId={email.accountId} threadId={email.threadId} mailbox={email.mailbox} />
```

Actualizar el `render` de `JunkBanner.autoAdvance.test.tsx` (l.62) para pasar `threadId="t2" mailbox="inbox"`, para que siga probando lo mismo que hoy.

- [ ] **Step 8: Verlo pasar**

Run: `npx vitest run src/components/EmailView/`
Expected: PASS.

- [ ] **Step 9: Gates y commit**

`gate-runner` `SET=commit`; `privacy-reviewer` `staged`.

```bash
git add src/components/EmailView/ src/locales/*/inbox.json
git commit -m "feat: offer Not spam on conversations filed in Spam"
```

---

### Task 4: Verificación end-to-end, docs y cierre

**Files:**
- Posible modificación: `docs/site/{en,es,fr,de}/…` (solo si `maintain-docs` encuentra prosa sobre Spam o "No es basura" que ahora sea falsa)
- Posible modificación: `docs/DECISIONS.md`

- [ ] **Step 1: Gates de push**

Subagente `gate-runner` con `SET=push` (cargo test completo, ambos clippy, cargo-outdated). Guardar la salida completa en el scratchpad; reportar el código de salida y la línea de resumen.

- [ ] **Step 2: Verificación en la app real (instancia demo)**

Skill `verify-emailops` sobre la base demo sintética, nunca el buzón real: abrir la vista Spam, abrir una conversación, pulsar "No es spam", comprobar que desaparece de Spam y aparece en Recibidos, y que en la fila de `email_junk` queda `user_override = 'not_junk'` (vía `make cli-fast ARGS="show <id> --json"` o, si la CLI no lo expone, `sqlite3` sobre la base demo). Si la demo no tiene correo en Spam, primero mover uno con "Confirmar basura" en la misma instancia. Capturas en el scratchpad.

- [ ] **Step 3: Docs y verificación**

Skill `maintain-docs` para comprobar si alguna frase publicada sobre Spam / "No es basura" ha quedado falsa, y `maintain-verification` para añadir el paso de la vista Spam al sweep si la vista está catalogada. Commit aparte si cambia algo: `docs: describe moving mail out of spam`.

- [ ] **Step 4: Decisión**

Añadir a `docs/DECISIONS.md` (formato de la cabecera del fichero): "Not spam moves the message back to the inbox at the provider". Contexto: el detector nunca mueve correo por su cuenta; una acción explícita del usuario sí, igual que "Confirmar basura". Alternativa rechazada: que "No es basura" solo quite la etiqueta local. Commit `docs: record the not-spam provider move decision`.

- [ ] **Step 5: Cierre**

`privacy-reviewer` con scope `branch`. No hacer push sin que el desarrollador lo pida.
