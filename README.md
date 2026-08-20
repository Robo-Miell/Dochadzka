# Flutter mobilná aplikácia

Mobilný klient pre Android/iOS.

## Prvé vytvorenie platformových súborov

V priečinku `mobile_flutter`:

```bash
flutter create . --platforms=android,ios
flutter pub get
```

Potom používaj existujúci `lib/main.dart` a `pubspec.yaml`.

## Vývoj

Android emulátor + lokálny server:

```bash
flutter run --dart-define=API_URL=http://10.0.2.2:8000
```

Fyzický mobil musí používať IP adresu PC/servera, napr.:

```bash
flutter run --dart-define=API_URL=http://192.168.1.50:8000
```

Online:

```bash
flutter run --dart-define=API_URL=https://dochadzka.firma.sk
```

## Release

Android:

```bash
flutter build apk --release --dart-define=API_URL=https://dochadzka.firma.sk
```

iOS:

```bash
flutter build ipa --release --dart-define=API_URL=https://dochadzka.firma.sk
```

iOS build vyžaduje macOS, Xcode a Apple signing.
