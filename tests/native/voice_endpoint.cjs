const assert = require('node:assert/strict');
const Endpoint = require('../../app/frontend/voice-endpoint.js');
function feed(e, from, until, rms) {
  for (let t = from; t < until; t += 20) assert.equal(e.update(rms, t), false);
}
let e = new Endpoint();
feed(e, 0, 1000, 0); // silence alone must never create a turn
feed(e, 1000, 1060, .03); // brief noise must not finish a turn
feed(e, 1060, 2400, 0);
e.reset();
feed(e, 0, 1000, .025);
feed(e, 1000, 1780, 0);
assert.equal(e.update(0, 1800), true); // short turn: 800 ms trailing silence
e.reset();
feed(e, 0, 3000, .025);
feed(e, 3000, 3900, 0); // longer speech gets room to pause
feed(e, 3900, 4100, .012); // quiet last word resets silence
feed(e, 4100, 5180, 0);
assert.equal(e.update(0, 5200), true);
console.log('Endpoint timing checks passed');
