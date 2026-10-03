/** Deterministic pseudo-random helpers so the same drill path always shows the same numbers. */

export function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function rng(seed: string): () => number {
  let a = hashStr(seed);
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Split `total` into n parts with concentrated (skewed) weights; parts always sum to total. */
export function splitAmount(total: number, n: number, seed: string, skew = 2.2): number[] {
  const r = rng(seed);
  const w = Array.from({ length: n }, () => Math.pow(0.15 + r(), skew));
  const sum = w.reduce((a, b) => a + b, 0);
  const parts = w.map((x) => (total * x) / sum);
  // fix rounding drift to 4dp so sums reconcile exactly
  const rounded = parts.map((p) => Math.round(p * 1e4) / 1e4);
  const drift = Math.round((total - rounded.reduce((a, b) => a + b, 0)) * 1e4) / 1e4;
  rounded[0] = Math.round((rounded[0] + drift) * 1e4) / 1e4;
  return rounded;
}

export const DEPARTMENTS = ["Menswear", "Womenswear", "Kidswear", "Footwear", "Accessories", "Home & Living"];
export const REGIONS = ["North", "South", "East", "West"];

export const STORES: Record<string, string[]> = {
  North: ["Rohini", "Karol Bagh", "Sector 18 Noida", "Gurugram MG Road", "Ludhiana Model Town", "Jaipur C-Scheme"],
  South: ["Koramangala", "T Nagar", "Banjara Hills", "Kochi Edappally", "Mysuru Devaraja", "Coimbatore RS Puram"],
  East: ["Salt Lake", "Park Street", "Patna Boring Road", "Bhubaneswar Saheed Nagar", "Guwahati GS Road", "Ranchi Main Road"],
  West: ["Andheri West", "Pune FC Road", "Surat Adajan", "Ahmedabad CG Road", "Indore Vijay Nagar", "Nagpur Sitabuldi"],
};

export const ALL_STORES: { name: string; region: string }[] = Object.entries(STORES).flatMap(([region, names]) =>
  names.map((name) => ({ name, region })),
);

export const VENDORS = [
  "Arvind Garments Pvt Ltd",
  "Raymond Apparel Ltd",
  "Bhilwara Textiles",
  "Siyaram Fashions",
  "Kora Footwear Co",
  "Metro Leather Works",
  "Sunrise Kidswear",
  "Orient Home Furnishings",
  "Vardhman Knits",
  "Trident Accessories",
  "Alok Denim Mills",
  "Shree Ganesh Hosiery",
  "Lotus Fabrics",
  "Pearl Embroidery House",
  "Navkar Trims",
  "Deccan Weaves",
  "Kalyani Outerwear",
  "Mohan Garment Exports",
  "Rathi Textiles",
  "Fabindia Sourcing Co",
];

export const AGEING_BUCKETS = ["0–30 days", "31–90 days", "91–180 days", "181–365 days", ">365 days"];
