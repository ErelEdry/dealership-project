// Bundled, dependency-free car silhouettes keyed by body_type. Side profiles
// (facing left) drawn as a single filled path with wheel arches + wheels, on a
// shared 640×256 viewBox. Rendered with fill=currentColor so callers control
// colour/opacity via text-* — kept monochrome so it reads as a quiet backlit
// shape behind the cyan match gauge.

// Two wheels sitting in arches, centred at (frontX, rearX), y=184, r=30.
const wheels = (frontX: number, rearX: number) =>
  `M${frontX} 184 m-30 0 a30 30 0 1 0 60 0 a30 30 0 1 0 -60 0` +
  `M${rearX} 184 m-30 0 a30 30 0 1 0 60 0 a30 30 0 1 0 -60 0`;

const SHAPES: Record<string, string> = {
  // three-box: hood · greenhouse · trunk
  sedan:
    "M60 150 L96 150 L150 122 L210 118 L252 82 L388 82 L440 118 L556 120 L580 150 L580 172 " +
    "L524 172 A34 34 0 0 0 456 172 L184 172 A34 34 0 0 0 116 172 L60 172 Z" +
    wheels(150, 490),

  // short rear ending in a steep hatch
  hatchback:
    "M60 150 L96 150 L150 122 L208 118 L250 82 L360 82 L430 104 L468 150 L468 172 " +
    "L454 172 A34 34 0 0 0 386 172 L184 172 A34 34 0 0 0 116 172 L60 172 Z" +
    wheels(150, 420),

  // tall, boxy, upright greenhouse
  suv:
    "M56 150 L92 148 L150 122 L182 116 L206 66 L440 66 L474 112 L500 146 L500 172 " +
    "L494 172 A34 34 0 0 0 426 172 L194 172 A34 34 0 0 0 126 172 L56 172 Z" +
    wheels(160, 460),

  // cab up front, long low open bed
  pickup:
    "M56 150 L92 148 L150 122 L182 118 L206 80 L322 80 L352 120 L352 132 L560 132 L580 148 L580 172 " +
    "L524 172 A34 34 0 0 0 456 172 L189 172 A34 34 0 0 0 121 172 L56 172 Z" +
    wheels(155, 490),

  // low nose, long fastback roofline
  coupe:
    "M64 152 L100 150 L180 130 L250 92 L330 88 L520 138 L548 158 L548 172 " +
    "L534 172 A34 34 0 0 0 466 172 L194 172 A34 34 0 0 0 126 172 L64 172 Z" +
    wheels(160, 500),

  // long roof carried all the way to a near-vertical tailgate
  wagon:
    "M60 150 L96 150 L150 122 L206 116 L248 80 L470 80 L500 96 L525 150 L525 172 " +
    "L524 172 A34 34 0 0 0 456 172 L184 172 A34 34 0 0 0 116 172 L60 172 Z" +
    wheels(150, 490),
};

// Dataset vocab → shape. `ute` is the pickup profile; `wagon` is the estate.
const ALIASES: Record<string, string> = { ute: "pickup", estate: "wagon" };

function pathFor(bodyType?: string | null): string {
  const key = (bodyType ?? "").toLowerCase().trim();
  const shape = SHAPES[key] ?? SHAPES[ALIASES[key]] ?? SHAPES.sedan;
  return shape;
}

export default function CarSilhouette({
  bodyType,
  className,
}: {
  bodyType?: string | null;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 640 256"
      className={className}
      fill="currentColor"
      aria-hidden
      focusable="false"
    >
      <path d={pathFor(bodyType)} />
    </svg>
  );
}
