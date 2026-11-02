/** Tiny longitudinal-dynamics model used only to generate believable mock race series. */
export interface MockCarPhysics {
  car_id: string;
  label: string;
  power_kw: number;
  mass_kg: number; // kerb + driver
  cd_a: number; // m²
  crr: number;
  drive_eff: number;
  traction_g: number; // usable longitudinal grip at launch (FWD)
  shift_loss_s: number; // dead time per upshift
  shift_speeds_kmh: number[];
}

export interface MockSeries {
  car_id: string;
  label: string;
  t: number[];
  v_kmh: number[];
  s_m: number[];
}

export function simulate(c: MockCarPhysics, distance = 402.3): MockSeries {
  const dt = 0.01;
  const rho = 1.2;
  const g = 9.81;
  let t = 0;
  let v = 0;
  let s = 0;
  let shiftUntil = -1;
  const shifts = [...c.shift_speeds_kmh];
  const out: MockSeries = { car_id: c.car_id, label: c.label, t: [0], v_kmh: [0], s_m: [0] };
  let nextSample = 0.25;
  while (s < distance && t < 40) {
    const vk = v * 3.6;
    if (shifts.length && vk >= shifts[0]!) {
      shifts.shift();
      shiftUntil = t + c.shift_loss_s;
    }
    const drag = 0.5 * rho * c.cd_a * v * v + c.crr * c.mass_kg * g;
    let drive = 0;
    if (t >= shiftUntil) {
      const powerLimited = (c.power_kw * 1000 * c.drive_eff) / Math.max(v, 0.5);
      const tractionLimited = c.traction_g * g * c.mass_kg;
      drive = Math.min(powerLimited, tractionLimited);
    }
    const a = (drive - drag) / c.mass_kg;
    v = Math.max(0, v + a * dt);
    s += v * dt;
    t += dt;
    if (t >= nextSample - 1e-9 || s >= distance) {
      out.t.push(round(t, 2));
      out.v_kmh.push(round(v * 3.6, 1));
      out.s_m.push(round(Math.min(s, distance), 1));
      nextSample += 0.25;
    }
  }
  return out;
}

export function timeToSpeed(sr: MockSeries, kmh: number): number | null {
  for (let i = 1; i < sr.t.length; i++) {
    if (sr.v_kmh[i]! >= kmh) {
      const v0 = sr.v_kmh[i - 1]!;
      const v1 = sr.v_kmh[i]!;
      const t0 = sr.t[i - 1]!;
      const t1 = sr.t[i]!;
      return round(t0 + ((kmh - v0) / (v1 - v0 || 1)) * (t1 - t0), 2);
    }
  }
  return null;
}

function round(x: number, d: number) {
  const f = 10 ** d;
  return Math.round(x * f) / f;
}
