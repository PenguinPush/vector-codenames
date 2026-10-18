// Original demo vocabulary. These categories only drive the placeholder bot.
export const WORD_GROUPS: Record<string, string[]> = {
  orbit: ["MOON", "STAR", "PLANET", "SATELLITE", "COMET", "ROCKET"],
  ocean: ["WAVE", "CORAL", "SHARK", "DIVER", "REEF", "WHALE"],
  woodland: ["TREE", "LEAF", "MOSS", "FOX", "ROOT", "DEER"],
  melody: ["PIANO", "FLUTE", "DRUM", "NOTE", "VIOLIN", "BAND"],
  kitchen: ["SPOON", "PLATE", "CHEF", "OVEN", "BREAD", "SALT"],
  royalty: ["CROWN", "KING", "QUEEN", "CASTLE", "KNIGHT", "THRONE"],
  winter: ["SNOW", "ICE", "SKI", "FROST", "COAT", "SLED"],
  journey: ["TRAIN", "TRACK", "PILOT", "PLANE", "TICKET", "MAP"],
  garden: ["ROSE", "SEED", "BEE", "TULIP", "SOIL", "PETAL"],
  workshop: ["NAIL", "HAMMER", "SAW", "DRILL", "WOOD", "BENCH"],
  classroom: ["BOOK", "DESK", "PENCIL", "PAPER", "LESSON", "SCHOOL"],
  theatre: ["STAGE", "ACTOR", "MASK", "CURTAIN", "SCRIPT", "SCREEN"],
};

export const WORDS = Object.values(WORD_GROUPS).flat();

export function shuffle<T>(values: T[], random = Math.random): T[] {
  const result = [...values];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}
