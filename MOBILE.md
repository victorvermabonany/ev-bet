# Mobile App Setup

This app is now installable as a PWA from the hosted Render URL and has a Capacitor config for native wrappers.

## PWA

Open `https://ev-bet.onrender.com` on your phone and use the browser's add-to-home-screen/install option.

Browser alerts work while the app is open. On iPhone, install the PWA and allow notifications when prompted.

## Capacitor

Install dependencies, then add and sync a native platform:

```bash
npm install
npm run cap:add:ios
npm run cap:sync
npm run cap:open:ios
```

For Android:

```bash
npm install
npm run cap:add:android
npm run cap:sync
npm run cap:open:android
```

The wrapper points at the production Render app through `capacitor.config.json`.
