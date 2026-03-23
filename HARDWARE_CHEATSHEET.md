# Dual-Tech 2026 Hardware Test Cheatsheet

Użyj poniższych komend, aby przetestować sprzęt bez uruchamiania pełnej misji.

### 1. Test UGV (Domyślny)
Najpełniejszy test (Kamera + GPS + Silniki).
```bash
python3 test_hardware.py ugv
```

### 2. Test UAV
Sprawdza Kamerę i GPS (jeśli podłączony). Pomija silniki (sterowane przez MAVLink/Pixhawk).
```bash
python3 test_hardware.py uav
```

### 3. Tryb MOCK (Test na laptopie bez sprzętu)
Wymusza tryb symulacji dla wszystkich komponentów przez zmienne środowiskowe.
```bash
DT_HAL__CAMERA__MODE=mock \
DT_HAL__GPS__MODE=mock \
DT_HAL__MOTORS__MODE=mock \
python3 test_hardware.py ugv
```

### 4. Wymuszenie źródła kamery (np. zewnętrzna USB)
Jeśli podłączyłeś kamerę USB i chcesz ją sprawdzić zamiast systemowej:
```bash
DT_HAL__CAMERA__USE_PICAMERA=false \
DT_HAL__CAMERA__SOURCE=1 \
python3 test_hardware.py ugv
```

### 5. Replay GPS (Testowanie logiki z pliku)
Jeśli masz log GPS z poprzedniego przejazdu:
```bash
DT_HAL__GPS__MODE=replay \
DT_HAL__GPS__LOG_FILE=logs/gps_track.log \
python3 test_hardware.py ugv
```

---
**Uwaga:** Silniki w teście `ugv` zostaną uruchomione tylko na **0.5 sekundy** dla każdego koła przy małej prędkości (0.3). Upewnij się, że robot ma miejsce lub jest podniesiony.
