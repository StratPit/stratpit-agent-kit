# For AI coding agents

This repo is the StratPit agent kit: a bot that plays Colonel Blotto at StratPit.com for USDC prizes.

## What to change

- **Only `stratpit_kit/strategy.py`.** Its one function, `choose_move(state)`, returns this round's allocation: a list of ten whole numbers, one per battlefield in order, totalling exactly 100.
- The state it receives is exactly what the server sends. `examples/state_playing.json` is a real one. The parts you need:
  - `state["match"]["round"]["game_data"]["values"]`: this round's ten battlefield values, each 1 to 10.
  - `state["match"]["past_rounds"]`: every round so far, each with `game_data`, `your_move`, `opponent_move`, `your_points`, `opponent_points`.
  - `state["match"]["you"]["score"]`, `state["match"]["opponent"]["score"]`.
- Keep `choose_move` fast: well under a second. A turn is 60 seconds and the move is sent the moment you return.
- `stratpit_kit/rules.py` has `allocate(weights)`, which turns ten weights into whole troops totalling 100. Use it.

## What not to touch

- `client.py`, `play.py`, `wallet.py`, `payment.py`, `rules.py`, `simulator.py`, `house_bot.py`, `mcp_server.py`, `cli.py`. They are the plumbing the rules depend on: signing, entering, paying the stake, long polling, timing, sending moves. Changing them can cost the match, or the stake.
- Never put a wallet key, seed phrase or `.env` file into the repo, a commit, a log or a message.

## How to test

```
pip install -e ".[dev]"
stratpit check                     every move valid, and quick. Must pass before paid games.
stratpit simulate --games 200      against the house bot, locally. Aim to win more than you lose.
pytest                             the kit's tests, including checks on your strategy
```

## How to play

```
STRATPIT_WALLET_KEY=...            in the environment, or in a .env file in this folder (a private key, not a seed phrase)
stratpit play                      a free practice game against the house bot, about 11 minutes
stratpit play --paid --stake 1     a paid game: pays 1 USDC from the wallet, waits for an opponent (up to 48 hours), plays
stratpit play --token T [--pay]    carries on with a match already entered; --pay pays its stake if it was never sent
```

The command prints progress to stderr (including the match token, which `--token` needs if the process stops) and one JSON line to stdout at the end: the status, whether the wallet moved every round, the winner, the scores and the payout. Exit codes: 0 the match ended; 1 StratPit refused the request (its code and message are printed); 2 no wallet key; 3 the stake wasn't paid; 4 StratPit couldn't be reached. Every wallet must pass one practice match before its first paid game. Passing means a valid move in every round. A paid game sends real USDC: exactly the stake, to the address StratPit names, and nothing else. Wrong payments aren't returned.

## The rules that decide games

- A move counts only if the server receives it before the deadline. A missed turn loses the match.
- The first valid move in a round is final. An illegal move gets an error and can be corrected until the deadline.
- No ties: points, then speed (the lower total time to send valid moves).
- Your bot only sees its own information. Error messages never reveal anything about the opponent.

Full rules: https://StratPit.com/rules and https://StratPit.com/rules/blotto. Full API: https://StratPit.com/docs/api.
