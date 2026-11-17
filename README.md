[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/bangandrii/gta6-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/bangandrii/gta6-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI Twitch CCU Forecaster

This is an entry for the make.fun bounty gta6-twitch-ccu-forecast-01 (https://make.fun/bounty/gta6-twitch-ccu-forecast-01).

## Method

The program reads the case's hour-1 print to establish baseline viewership. It builds log-ratio curves of the release day from the case's past-launch comparables. Comparables are weighted by the similarity of their hour-1 size. Finally, it blends weighted empirical quantiles with a weighted normal fit per hour.

## Run

```bash
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Built with the make.fun kit. Referral: https://make.fun/r/rj8w1xf3 (the author's own referral link).
