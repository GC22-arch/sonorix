# Sonorix · TECH // SOUND

Dictado por voz para Windows, y también desde el celular. Hablas y el texto aparece donde esté tu cursor, en cualquier app. Es una alternativa a Wispr Flow que corre en tu PC.

## Inicio rápido

1. **Activa el micrófono para apps de escritorio**: *Configuración → Privacidad y seguridad → Micrófono → "Permitir que las aplicaciones de escritorio accedan al micrófono"*. Sonorix te avisa si está bloqueado.
2. Doble clic en **`Sonorix.bat`**. La primera vez instala todo (~1 min) y abre el panel.
3. Crea tu API key gratis en <https://console.groq.com/keys> (no pide tarjeta) y pégala en **Ajustes**.
4. Para dictar:
   - **Mantén `Ctrl derecho`** mientras hablas y suelta para pegar el texto.
   - **Toca `Ctrl derecho` dos veces** para el modo manos libres. Un toque más termina y `Esc` cancela.

## Costo: $0

| Motor | Precio | Notas |
|---|---|---|
| **Automático** (predeterminado) | Gratis | Usa la capa gratuita de Groq. Si se agota el cupo o no hay internet, cambia al motor local. |
| Groq `whisper-large-v3-turbo` | Gratis con límites (pagando serían $0,04/h) | La capa gratuita alcanza para horas de dictado por día. |
| Local `faster-whisper` | Gratis y sin conexión | Se instala con `instalar-local.bat` (~1 GB con el modelo). |

La limpieza con IA (quita muletillas y arregla la puntuación) usa un LLM de Groq y también entra en la capa gratuita.

## Funciones

- Píldora flotante con forma de onda en vivo, temporizador e indicador de manos libres. No roba el foco y los clics la atraviesan.
- Pegado instantáneo con Ctrl+V. Después restaura tu portapapeles. También hay un modo que escribe tecla a tecla.
- Atajo inteligente: si mantienes la tecla y pulsas otra (Ctrl+C, por ejemplo), no graba.
- Comandos de voz: "nueva línea", "nuevo párrafo", "punto y aparte", "dos puntos", "abre/cierra interrogación"…
- Vocabulario propio y reemplazos ("mi correo" → `tu@email.com`).
- Filtro contra las alucinaciones típicas de Whisper ("Subtítulos por Amara.org", "Gracias por ver").
- Historial en SQLite con búsqueda, copia, texto original y final, y exportación a CSV.
- Panel en <http://localhost:5000>: palabras, tiempo ahorrado, palabras por minuto, latencia, racha de días y apps donde más dictas.
- Icono en la bandeja del sistema (abrir panel, pausar, salir) y opción de iniciar con Windows.

## Modo celular

En el panel, ve a **Celular**, activa el modo y escanea el QR con el celular conectado a la misma red wifi.

- La primera vez, el navegador avisa que el certificado es autofirmado. Es el de tu PC: toca *Avanzado → Continuar*.
- Toca el botón para dictar, o mantenlo pulsado para hablar y soltar. El texto se copia al portapapeles del celular.
- Si activas **"Pegar también en el PC"**, el celular funciona como teclado remoto.
- Puedes instalarla como app con *Agregar a pantalla de inicio*.
- Solo entran los dispositivos emparejados con el token del QR. Con "Desemparejar" lo invalidas.
- Si no conecta, permite Python en el Firewall de Windows para redes privadas.

## Archivos

```
Sonorix.bat            arranca la app (crea el entorno en %USERPROFILE%\.sonorix\venv)
Sonorix-debug.bat      igual, pero con consola para ver errores
instalar-local.bat     motor offline gratis (faster-whisper)
sonorix/
  app.py               orquestador: atajo → audio → transcripción → limpieza → pegado
  hotkey.py            mantener / doble toque / combos (entiende nombres de tecla en español)
  recorder.py          micrófono a 16 kHz, detección de voz, FLAC
  transcriber.py       Groq Whisper, faster-whisper, limpieza con LLM
  postprocess.py       comandos de voz, reemplazos, filtro de alucinaciones
  overlay.py           píldora flotante (tkinter + Win32)
  db.py                historial SQLite + estadísticas
  web.py               panel localhost:5000 (protegido contra CSRF y DNS rebinding)
  mobile.py            servidor HTTPS para el celular + QR + token
  static/              panel, PWA del celular, logo
```

Los datos (ajustes, historial y log) están en `%LOCALAPPDATA%\Sonorix`, fuera de OneDrive, para que la sincronización no bloquee la base de datos.

## Notas

- Si la ventana activa se ejecuta como administrador, Windows no deja que Sonorix lea el atajo en ella. Para eso habría que abrir Sonorix también como administrador.
- Puedes cambiar la tecla en *Ajustes → Atajo → Cambiar…* y pulsar la que quieras. Buenas opciones: `right ctrl`, `right alt`, `f8`.
