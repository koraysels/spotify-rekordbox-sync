use std::io::{BufRead, BufReader, Write};
use std::net::TcpListener;
use std::time::Duration;

/// Wait for Spotify's OAuth redirect on a loopback port and return the code.
///
/// Spotify requires a real redirect URI for PKCE, and desktop apps are expected
/// to use a loopback address. Rather than shipping a browser or a hosted
/// callback, the app listens on localhost just long enough to catch the single
/// redirect, then shuts the listener down.
#[tauri::command]
async fn oauth_listen(port: u16, timeout_secs: u64) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let listener = TcpListener::bind(("127.0.0.1", port))
            .map_err(|e| format!("could not listen on port {port}: {e}"))?;
        listener
            .set_nonblocking(false)
            .map_err(|e| format!("could not configure listener: {e}"))?;

        let deadline = std::time::Instant::now() + Duration::from_secs(timeout_secs);
        for stream in listener.incoming() {
            if std::time::Instant::now() > deadline {
                return Err("timed out waiting for Spotify sign-in".into());
            }
            let mut stream = match stream {
                Ok(s) => s,
                Err(e) => return Err(format!("connection failed: {e}")),
            };

            let mut request_line = String::new();
            BufReader::new(&stream)
                .read_line(&mut request_line)
                .map_err(|e| format!("could not read redirect: {e}"))?;

            let body = "<html><body style=\"font-family:system-ui;padding:3rem\">\
                <h2>Signed in.</h2><p>You can close this tab and return to the app.</p>\
                </body></html>";
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\n\r\n{}",
                body.len(),
                body
            );
            let _ = stream.write_all(response.as_bytes());
            let _ = stream.flush();

            // Request line looks like: GET /callback?code=... HTTP/1.1
            let target = request_line.split_whitespace().nth(1).unwrap_or("");
            if let Some(query) = target.split('?').nth(1) {
                for pair in query.split('&') {
                    let mut parts = pair.splitn(2, '=');
                    let key = parts.next().unwrap_or("");
                    let value = parts.next().unwrap_or("");
                    if key == "code" {
                        return Ok(urldecode(value));
                    }
                    if key == "error" {
                        return Err(format!("Spotify returned an error: {}", urldecode(value)));
                    }
                }
            }
            return Err("redirect contained no authorization code".into());
        }
        Err("listener closed before a redirect arrived".into())
    })
    .await
    .map_err(|e| format!("oauth listener panicked: {e}"))?
}

fn urldecode(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or("");
                match u8::from_str_radix(hex, 16) {
                    Ok(byte) => {
                        out.push(byte);
                        i += 3;
                    }
                    Err(_) => {
                        out.push(bytes[i]);
                        i += 1;
                    }
                }
            }
            b'+' => {
                out.push(b' ');
                i += 1;
            }
            byte => {
                out.push(byte);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![oauth_listen])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
