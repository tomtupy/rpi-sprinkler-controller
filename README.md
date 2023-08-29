# rpi-sprinkler-controller
Sprinkler Controller for Raspberry Pi

`NEW_RELIC_ENVIRONMENT=production NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program python sprinkler.py`

<img width="843" alt="Screenshot 2023-08-28 205755" src="https://github.com/tomtupy/rpi-sprinkler-controller/assets/7709362/6e92b63b-c3ca-49b8-94d2-f82207d1f0f4">

## Failsafe Circuit
Because this program controls a live irrigation system, a failure has the potential to rack up a big water bill and/or cause a flood.
Pretty much any failure mode will result in the GPIO pin getting stuck in HIGH or LOW.
A good solution here is to enable power to the relay board only if the program is pulsing a pin between HIGH and LOW at some interval. If the signal stays HIGH or LOW past the expected interval, the circuit will time out and cut power to the relay board (and therefore all solenoids controlling water will lose power).

A good circuit for this is described here: https://forums.raspberrypi.com/viewtopic.php?t=185076#p1171118
![image](https://github.com/tomtupy/rpi-sprinkler-controller/assets/7709362/644275bf-c846-47d3-ad8e-e08f6f007e2a)

The output of the circuit keeps a master relay open if the input is being pulsed. The master relay controls power to the relay board.
