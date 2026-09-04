type AnimatedGlobeProps = {
    className?: string;
};

const NODES = [[126, 93], [185, 72], [231, 116], [158, 143], [99, 158], [210, 172], [258, 152], [145, 205], [82, 120]];

export default function AnimatedGlobe({ className = "" }: AnimatedGlobeProps) {
    return (
        <svg aria-label="Animated global evidence network" className={className} fill="none" role="img" viewBox="0 0 340 280">
            <title>Global evidence network</title>
            <g className="animate-globe-turn">
                <circle cx="170" cy="140" r="108" className="fill-(--mechanism-edge) stroke-(--mechanism-line)" strokeWidth="1" />
                <ellipse cx="170" cy="140" rx="54" ry="108" className="stroke-(--mechanism-line)" strokeWidth="1" />
                <path d="M62 140h216M77 92h186M77 188h186" className="stroke-(--mechanism-line)" strokeWidth="1" />
                <path d="M90 67c45 30 115 30 160 0M90 213c45-30 115-30 160 0" className="stroke-(--mechanism-line)" strokeWidth="1" />
                <path d="M83 136C119 77 204 72 260 119M91 176c50 38 124 24 165-34M115 71c37 50 101 81 157 53" className="animate-globe-route stroke-(--secondary-color)" strokeDasharray="5 7" strokeWidth="2" />
                {NODES.map(([cx, cy]) => <circle className="animate-globe-node fill-(--primary-color)" cx={cx} cy={cy} key={`${cx}-${cy}`} r="4" />)}
            </g>
            <circle cx="170" cy="140" r="122" className="animate-globe-pulse stroke-(--primary-color)" strokeWidth="1" />
        </svg>
    );
}
