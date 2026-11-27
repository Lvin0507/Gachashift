Real log excerpts the tests read, trimmed to the lines the parsers use. Account ids and
other personal details are removed. When a report looks wrong, add the day's log here and
a test for what the report should have said, then fix the parser until the test passes.

| File | Tool | What happened that day |
|---|---|---|
| `bettergi_2026-11-13.log` | BetterGI | 4/4 commissions, reward claimed |
| `bettergi_2026-11-14.log` | BetterGI | 3/4 (one commission has no route), reward not claimed |
| `bettergi_2026-11-15.log` | BetterGI | 3/4 (one commission has no route), reward not claimed |
| `bettergi_2026-11-27.log` | BetterGI 0.67, commission script 1.0.5 | no progress line, only the list of commissions: 4/4, reward claimed |
| `bettergi_2026-11-27_mondstadt.log` | BetterGI 0.67 | a misread commission skipped (3/4); game closed during the first domain |
| `bettergi_2026-11-27_domain.log` | BetterGI 0.67 | a domain started by hand, cancelled after one reward |
| `onedragon_2026-11-15.log` | OneDragon | 8 apps done; the log file was new that morning |
| `onedragon_2026-11-27.log` | OneDragon | 7 apps done, 活跃度奖励 failed; the log file was new that morning and the stall check hid it |
| `okww_2026-11-13.log` | ok-ww | Weekly garden already at the cap |
