# Trakt ↔ Letterboxd Sync

> **Trakt-authoritative automated synchronization with a Letterboxd CSV bridge.**

A self-hosted service designed to maintain synchronized movie watch history, view dates, rewatches, and ratings between **Trakt** and **Letterboxd**, backed by an internal database serving as the canonical source of truth.

---

## 1. What the Project Does

- **Automated Trakt Synchronization**: Automatically polls and synchronizes movie viewing history and ratings with Trakt every 15 minutes (or on demand) using Trakt's official v2 API.
- **Letterboxd CSV Import & Export Bridge**: Imports official Letterboxd data exports (`diary.csv`, `ratings.csv`, `watched.csv`, or full ZIP archives) and exports Trakt-originated updates in a Letterboxd-compatible CSV format.
- **Discrete Event-Based Watch History**: Tracks individual viewing dates and rewatches instead of a flat watch count.
- **Strict Canonical Rating Conversion**: Maintains ratings on the canonical Letterboxd half-star scale ($0.5$ to $5.0$) internally, converting bidirectionally to/from Trakt's integer scale ($1$ to $10$).
- **Idempotency & Loop Prevention**: Uses SHA-256 semantic content hashing and deterministic idempotency keys to guarantee that repeated sync runs produce zero unintended duplicates or infinite sync loops.
- **Three-Way Conflict Resolution**: Detects rating divergence between Trakt, Letterboxd, and the internal baseline, offering a dedicated interactive resolution dashboard.
- **Dry-Run Analysis**: Provides non-destructive simulation (`POST /api/sync/dry-run`) before committing mutations.

---

## 2. What It Cannot Currently Do

- **No Real-Time Direct API Writes to Letterboxd**: Does not write directly to Letterboxd's servers in real-time, because Letterboxd does not provide public personal API write access.
- **Movies Only (MVP Scope)**: TV shows, episodes, seasons, collections, lists, comments, likes, and followers are intentionally excluded from the MVP.
- **No Bypassing of Provider Rules**: Does not scrape undocumented internal private endpoints.

---

## 3. Why Letterboxd Requires a CSV Bridge

Letterboxd's official API is strictly request-only and restricted to commercial partners. It is not generally available for personal or self-hosted developer keys. The only officially supported, machine-readable mechanisms for personal accounts are:
1. **Account Data Export** (under *Settings > Data > Export your data*), which outputs standard CSV files.
2. **Data Import** (under *Settings > Data > Import your data*), which accepts formatted CSV files up to 1 MB.

This project implements a normalized provider abstraction (`LetterboxdProvider` implementing `Provider` ABC). When an official Letterboxd API is made publicly available, the service can switch to direct API calls without altering the core synchronization engine.

---

## 4. How Trakt OAuth Works

1. The service never asks for or stores Trakt passwords.
2. Clicking **Connect Trakt** in the dashboard directs the user to `https://trakt.tv/oauth/authorize` with a unique, cryptographically random `state` parameter to prevent CSRF attacks.
3. Upon approval, Trakt redirects back to `/auth/trakt/callback` with an authorization code.
4. The service exchanges this code with Trakt's token endpoint for an `access_token` and `refresh_token`.
5. Tokens are encrypted using symmetric Fernet encryption before being persisted to the database. They are never exposed in API responses or log output.
6. An automatic refresh cycle refreshes access tokens when nearing expiration.

---

## 5. How to Export Letterboxd Data

1. Log into your account at [letterboxd.com](https://letterboxd.com).
2. Go to **Settings** ➔ **Data** ➔ click **Export your data**.
3. Letterboxd will generate and download a `.zip` archive containing:
   - `diary.csv` (contains viewing dates, ratings, and rewatches)
   - `ratings.csv` (contains ratings)
   - `watched.csv` (contains watch statuses)
4. You can upload the `.zip` directly to this service, or upload any individual `.csv` file.

---

## 6. How to Import Letterboxd Data

1. Open the local dashboard at `http://localhost:8000`.
2. Under **Letterboxd Data Import**, click **Choose File** and select your exported `.zip` or `.csv` file.
3. Click **Run Dry-Run** to preview new watches, rating updates, and potential conflicts without altering your data.
4. Click **Import & Sync** to apply changes transactionally.

---

## 7. How Trakt Changes Are Exported for Letterboxd

1. When new viewings or rating updates occur on Trakt, the service updates the canonical internal database.
2. Click **Export for Letterboxd** in the dashboard (or send a `GET` request to `/api/letterboxd/export`).
3. The service downloads a Letterboxd-compatible CSV with headers:
   ```text
   Title,Year,tmdbID,imdbID,Rating,WatchedDate
   ```
4. Navigate to Letterboxd ➔ **Settings** ➔ **Data** ➔ **Import your data** and upload this generated CSV.

---

## 8. Rating Conversion Pipeline

Canonical storage strictly uses the Letterboxd scale ($0.5$ to $5.0$ in $0.5$ increments). Provider adapters convert at their boundaries:

$$\text{Trakt} = \text{round}(R_{\text{canonical}} \times 2)$$

$$R_{\text{canonical}} = \frac{R_{\text{trakt}}}{2}$$

| Canonical (Letterboxd) | Trakt Rating (1–10) |
| :---: | :---: |
| 0.5 ★ | 1 |
| 1.0 ★ | 2 |
| 1.5 ★ | 3 |
| 2.0 ★ | 4 |
| 2.5 ★ | 5 |
| 3.0 ★ | 6 |
| 3.5 ★ | 7 |
| 4.0 ★ | 8 |
| 4.5 ★ | 9 |
| 5.0 ★ | 10 |
| None | None |

*Letterboxd 4.5 converts to Trakt 9, never truncated to 4.*

---

## 9. Watch-Event Handling

Watch history is represented as discrete viewing events rather than a single counter:
- Each viewing date is preserved as an individual `WatchEvent` record.
- Multiple viewings (rewatches) maintain their individual calendar dates.
- `watched` is derived from `len(watch_events) > 0`.
- `watch_count` is derived dynamically from `len(watch_events)` and is never stored as an authoritative primary field.
- Re-importing the same CSV multiple times detects duplicate events via deterministic event IDs (`{provider}:{movie_id}:{watched_date}`) and prevents duplication.

---

## 10. Conflict Resolution

When ratings diverge:
- **Equivalent Ratings**: Letterboxd 4.5 and Trakt 9 are recognized as equal. No conflict.
- **One-Sided Addition**: A new rating on one provider is safely propagated without deleting existing data.
- **Missing Rating Protection**: If Letterboxd has a rating and Trakt is unrated, the Letterboxd rating is never deleted.
- **True Conflict**: If both providers have changed to different values from the baseline and timestamps cannot resolve the order, a conflict record is created.
- **Interactive Resolution**: Conflicts appear in the dashboard tab:
  `[ Keep Letterboxd ]  [ Keep Trakt ]  [ Keep Previous ]`
  Selecting an option updates the canonical record, generates necessary sync operations, and logs the decision.

---

## 11. Initial Synchronization

When connecting Trakt and importing Letterboxd for the first time:
1. Default behavior is a non-destructive **MERGE**.
2. Neither remote provider's data is erased.
3. Dry-run allows reviewing counts of new events, rating changes, and unmatched titles before writing changes to Trakt.

---

## 12. Docker Deployment

### Prerequisites
- Docker and Docker Compose installed.

### Quick Start
1. Clone the repository and copy the environment file:
   ```bash
   cp .env.example .env
   ```
2. Configure `TRAKT_CLIENT_ID` and `TRAKT_CLIENT_SECRET` in `.env`.
3. Start the application:
   ```bash
   docker compose up -d
   ```
4. Access the web dashboard at:
   ```text
   http://localhost:8000
   ```

---

## 13. Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite+aiosqlite:///./data.db` |
| `TRAKT_CLIENT_ID` | Trakt API application client ID | `""` |
| `TRAKT_CLIENT_SECRET` | Trakt API application client secret | `""` |
| `TRAKT_REDIRECT_URI` | OAuth callback endpoint | `http://localhost:8000/auth/trakt/callback` |
| `TMDB_API_KEY` | Optional TMDb API key for fallback matching | `""` |
| `SECRET_KEY` | Encryption key for OAuth tokens and sessions | Random 32-byte string |
| `SYNC_INTERVAL_MINUTES` | Frequency of background Trakt polling | `15` |
| `LETTERBOXD_USERNAME` | Optional Letterboxd handle for RSS discovery | `""` |

---

## 14. Security Considerations

- **Tokens Encrypted at Rest**: OAuth tokens are encrypted using symmetric Fernet keys before database storage.
- **No Password Collection**: Passwords for Trakt and Letterboxd are never requested or stored.
- **Token Masking**: Tokens are filtered out of all API responses, serializations, and logs.
- **OAuth CSRF State**: Strict random state validation during authorization handshakes.
- **Safe Error Reporting**: Internal stack traces are suppressed in user-facing HTTP responses.

---

## 15. Current Limitations

1. **Letterboxd Manual Step**: Letterboxd requires manual CSV export/import steps until official API write access becomes available.
2. **Movie Focus**: TV show tracking is deferred to a future phase.
3. **Trakt Rate Limits**: Adheres to Trakt's default rate limits with exponential backoff on HTTP 429.

---

## 16. Future Letterboxd API Integration

The application follows clean architectural boundaries:
```
Provider (Abstract Interface)
├── TraktProvider (Direct HTTP API)
└── LetterboxdProvider (CSV Bridge -> Direct HTTP API)
```
When Letterboxd releases a public API, only `app/providers/letterboxd.py` requires updates to implement direct HTTP calls; the synchronization engine, conflict resolver, canonical database, and scheduler will remain unchanged.
