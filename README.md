# SunCast

SunCast is a weekly sunset forecast. You give it a place, and it returns seven days of weather around sunset, a 1–10 aesthetic score for each evening, nearby viewpoints, and an optional picture of what that sky might look like. A second tab lets people share those evenings with friends.

The app is a React interface talking to a Flask API. The same interface runs in a browser and, through Capacitor, as an iPhone or Android app.

## How a forecast is made

Opening the Forecast tab starts this chain.

1. **Place.** On launch the app asks the device for its location. In the browser that is the Geolocation API. On a phone it is the Capacitor geolocation plugin, which also asks for permission. The coordinates are turned into a place name. If location is unavailable, the forecast starts at Austin, Texas. Typing a city and submitting uses that name instead, and the backend looks up the coordinates so the label and the weather stay on the same place.

2. **Weather near sunset.** `POST /api/week` asks Open-Meteo for an hourly forecast and for each day's sunset time. The pipeline keeps the hour closest to sunset, not the conditions right now and not the daily high. Cloud cover, humidity, wind, visibility, temperature, pressure, and the chance of rain from that hour are what the rest of the forecast is based on.

3. **What the sky will look like.** Those numbers, plus a simple season value, go into a gradient-boosting model. The model predicts four visual properties: hue (where the color sits from red through gold), saturation, brightness, and cloud density. A saved model is loaded from `model/sunset_model_real_v1.pkl` when that file is present. If it is missing, the server trains a stand-in model from synthetic samples so the API can still answer.

4. **The 1–10 score.** The aesthetic score is not a second weather model. It is a weighted reading of the visual prediction: vivid color, brightness, warm red-to-gold hues, and partial cloud cover (about 20–55%) raise the score. A clear sky or a heavy overcast lowers it. Visibility adds a small amount. The result is clipped to 1–10 and labeled Muted, Fair, Good, Excellent, or Exceptional. The highest day in the week is marked as the best evening.

5. **Viewpoints.** The same coordinates are sent to `POST /api/viewpoints`. OpenStreetMap is searched for viewpoints and peaks within about 25 km. Open-Meteo supplies elevation. Each spot comes back with distance, compass direction, and a maps link. If nothing is mapped nearby, the API suggests heading toward open west-facing ground.

6. **A picture of the evening.** Each day also gets a short visual description and a text prompt built from the predicted colors and the place name. `POST /api/generate-image` turns that prompt into an image. If a Replicate token is set, it uses a hosted text-to-image model. Otherwise it tries Pollinations, and if that is unavailable it paints a sky locally with Pillow from the hue, saturation, brightness, and cloud values, so the screen still has a picture.

7. **On a phone, a reminder.** If the app is running natively and any evening scores 7.5 or higher, it schedules a local notification for 3:00 p.m. on that day. The note names the score, the place, and the top viewpoint. This does not run in the browser.

The week strip, the selected day's weather, the color preview, the viewpoint list, and the rendition are all views of that one response. Changing the place runs the chain again.

## The two screens

`frontend/src/App.jsx` is the shell: a Forecast tab, a Social tab, and the footer. Forecast is `sunsetPredictor.jsx`. Social is `Social.jsx`. Both call the API through `frontend/src/api.js`.

### Forecast

The hero accepts a place name or a "use my location" request. The week strip shows each day's score. Selecting a day shows sunset time, the weather snapshot from that evening, the predicted colors, and the viewpoints. Asking for a rendition sends that day's prompt and color values to the API. The handler that returns an image URL is `POST /api/generate-image`.

### Social

Social is a separate store, not a feature of the weather model. Accounts, friendships, and posts live in SQLite at `backend/data/suncast_social.db`. Photos sit in `backend/uploads` and are served at `/uploads/<filename>`.

- Sign in or create an account. The session is a bearer token kept in the browser as `suncast_token`.
- Search for someone by name or username and send a friend request. Sent requests stay listed as pending. If that person already requested you, adding them accepts the request.
- Incoming requests can be accepted or declined.
- Post a sunset photo with a place and a caption. The feed shows your posts and posts from accepted friends.
- Your profile holds your photo, name, and username, every post you can edit, and a friend count that opens the full friends list.

## Where the code lives

| Piece | Role |
| --- | --- |
| `frontend/src/App.jsx` | Tabs and page chrome |
| `frontend/src/sunsetPredictor.jsx` | Week forecast, viewpoints, rendition |
| `frontend/src/deviceLocation.js` | GPS on the web and on a phone, then a place name |
| `frontend/src/notifications.js` | Local alerts for high-scoring evenings on a phone |
| `frontend/src/Social.jsx` | Accounts, friends, feed, profile |
| `frontend/src/api.js` | API address, auth header, and fetch helper |
| `backend/App.py` | Flask API that joins weather, the model, images, viewpoints, and social |
| `backend/model/sunset_data_pipeline.py` | Geocoding, Open-Meteo forecast, sunset-hour snapshots, solar geometry |
| `backend/model/sunset_ml_models.py` | Gradient-boosting model, prompt text, and the 1–10 score |
| `backend/model/image_generator.py` | Hosted image APIs, with a local Pillow sky as the fallback |
| `backend/viewpoints.py` | Overlooks and peaks from OpenStreetMap |
| `backend/social_store.py` | Users, friendships, and posts |
| `frontend/ios` and `frontend/android` | Capacitor shells that load the built web app |

`SunsetCNNModel` in the model file is an unused sketch. The running forecast uses gradient boosting only.

## Browser and phone

In the browser the API is `http://localhost:5001`. The Flask app listens on all interfaces, port 5001.

A phone cannot use localhost, because that name means the phone itself. The native build uses the computer's Wi-Fi address in `frontend/src/api.js` (`DEVICE_API_BASE`) and in `frontend/.env.production` (`REACT_APP_API_URL`). The phone and the computer need to be on the same Wi-Fi, and the backend has to be running before the app is opened. If the computer's IP changes, update both places, then rebuild and sync:

```bash
cd frontend
npm run build && npx cap sync ios
```

Open `frontend/ios/App/App.xcodeproj` in Xcode and run it on the device. `npm run mobile:ios` builds, syncs, and opens the Xcode project. Android follows the same pattern with `npm run mobile:android`.

## Run it locally

Backend, from the repo root:

```bash
cd backend
../venv/bin/python App.py
```

Frontend, in another terminal:

```bash
cd frontend
npm install
npm start
```

The site is at `http://localhost:3000`. Optional environment variables for the backend:

| Variable | Effect |
| --- | --- |
| `PORT` | API port. Default `5001`. |
| `MODEL_PATH` | Trained model file. Default `model/sunset_model_real_v1.pkl`. |
| `REPLICATE_API_TOKEN` | Enables hosted image generation. Without it, the local sky renderer is used. |
| `IMAGE_PROVIDER` | `auto`, `replicate`, or `pollinations`. |
| `SOCIAL_DB_PATH` | SQLite file for accounts and posts. |

Weather, geocoding, elevation, and map data come from Open-Meteo and OpenStreetMap and do not need keys.
