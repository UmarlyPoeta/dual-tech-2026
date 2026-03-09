# Oprogramowanie

## Finite State Machine (FSM):
- TRANSPORT: Stan przygotowania ruchu.
- RELEASE: Stan otwierania chwytaka.

## Pseudokod kontrolera:
- UGV: Kontrola napędu i chwytaka.
- UAV: Kontrola wciągarki i uwolnienia ładunku.

## Weryfikacja chwytu:
- Prąd serwa (MG995/SG90): Analiza siły chwytu.
- Pozycja kątowa.
- YOLO: Detekcja obiektów na podstawie bounding boxów.

## Klasa GripperController (Python):
- Metody: open(), close(), verify(), release().