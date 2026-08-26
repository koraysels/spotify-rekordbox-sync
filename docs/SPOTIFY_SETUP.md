# Connecting your Spotify account

You need a **Client ID** before the app can sign in. This is a one-time,
three-minute setup.

## Why is this needed?

Spotify has no generic "log in to any app" button. Every application that talks
to the Spotify API has to be registered, and Spotify's login page needs to know
*which* application is asking. The Client ID is that identifier.

To be clear about what it is and is not:

- It is **not** a password, and it is **not** the "Client secret".
- It identifies the **app**, not you. It appears in the address bar of the
  Spotify login page every desktop and mobile app opens.
- You still log in on Spotify's own page, with your own account. The app never
  sees your password.

This app uses PKCE, the authorization flow designed for desktop apps, which is
why no secret is required.

## Create the app

1. Go to <https://developer.spotify.com/dashboard> and **Log in** with your
   normal Spotify account.
2. Accept the Developer Terms if prompted. First time only.
3. Click **Create app**.
4. Fill in:

   | Field | Value |
   |---|---|
   | App name | `rbsync` (anything) |
   | App description | `Sync Spotify playlists to rekordbox` (anything) |
   | Redirect URI | `http://127.0.0.1:8888/callback` |
   | Which API/SDKs | tick **Web API** |

   The Redirect URI must match **exactly**, and you must press **Add** so it
   appears as a listed entry rather than just text in the box.

   Use `127.0.0.1`, **not** `localhost` — Spotify rejects `localhost` for
   loopback redirects.

5. Tick the terms checkbox and click **Save**.

## Copy the Client ID

1. On the app page, click **Settings** (top right).
2. Under **Basic Information**, copy the **Client ID**.
3. Ignore **Client secret**. This app never uses it — don't share it with
   anyone, including with this app.

## Put it in the app

1. Open rbsync → **Settings**.
2. Paste the Client ID into the Spotify field.
3. **Save**, then **Sign in with Spotify**.

Your browser opens Spotify's login page. Approve, and the tab tells you it is
done. The app stores the resulting token locally, so this is a one-time step.

## Sharing with other people

A Spotify app in Development Mode allows **5 authenticated users total**,
including you, and each must be added by hand.

To add someone: your app page → **User Management** → add their name and the
email address on their Spotify account. The app owner also needs Spotify
Premium.

Extended Quota Mode lifts the limit, but Spotify grants it only to registered
organizations with a launched product and 250,000+ monthly active users, so it
is not an option for a personal tool.

Beyond five people, each additional person should create their **own** free
Spotify app with these same steps and paste their own Client ID. There is no
limit on that route.

## Troubleshooting

**"INVALID_CLIENT: Invalid redirect URI"**
The Redirect URI in the dashboard does not exactly match
`http://127.0.0.1:8888/callback`. Check for a trailing slash, `localhost`
instead of `127.0.0.1`, or that you forgot to press **Add**.

**The browser opens but the app never continues**
Something else is using port 8888. Quit it and sign in again.

**All playlists show 0 tracks**
An old build. Spotify changed the playlist API; update to a current build.

**Some of my playlists are missing from the list**
By default the app hides playlists Spotify refuses to serve. Turn off
**Settings → Playlists → "Only show playlists I can sync"** to list them all;
they will still fail to sync, but you can see them.

**A playlist shows "n/a" and won't sync**
Spotify only returns the contents of playlists you **own or collaborate on**.
Playlists you merely follow answer 403 and cannot be read at all — this is a
Spotify restriction introduced in February 2026, not something the app can work
around. To sync one, open it in Spotify and duplicate it into your own account
("Add to your library" is not enough — you need your own copy), then sync that.
