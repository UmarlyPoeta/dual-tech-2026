# Elektronika

## Komponenty sterujące:
- PCA9685 (I2C): Kontrola serw (MG995 + SG90).
- TMC2209: Sterownik silnika krokowego NEMA17.
- L298N: Sterownik dwóch silników DC (napęd gąsienic).

## Schemat zasilania:
- Źródło: LiPo 3S.
- Regulatory typu buck: Zasilanie Raspberry Pi 5, serw i silnika krokowego.

## Pinout Raspberry Pi 5:
- I2C: SDA=GPIO2, SCL=GPIO3.