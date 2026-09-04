"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useRef, useSyncExternalStore } from "react";
import { BackSide, type Group, QuadraticBezierCurve3, Vector3 } from "three";

type Palette = Record<"mechanism" | "edge" | "line" | "primary" | "secondary" | "surface" | "muted", string>;

const NODES = [[0.55, 0.6, 1.46], [-1.1, 0.25, 1.18], [1.1, -0.15, 1.18], [-0.25, -0.95, 1.28], [0.2, 1.05, 1.2], [-1.3, -0.72, 0.78]]
    .map(([x, y, z]) => new Vector3(x, y, z).normalize().multiplyScalar(1.78));
const ROUTES = [[0, 1], [0, 2], [0, 4], [1, 5], [2, 3], [3, 5]].map(([from, to]) => {
    const start = NODES[from];
    const end = NODES[to];
    const control = start.clone().add(end).normalize().multiplyScalar(2.35);
    return new QuadraticBezierCurve3(start, control, end);
});
let paletteSnapshot: Palette | null = null;

function getPalette() {
    if (paletteSnapshot) return paletteSnapshot;
    const styles = getComputedStyle(document.documentElement);
    paletteSnapshot = {
        mechanism: styles.getPropertyValue("--mechanism-color").trim(),
        edge: styles.getPropertyValue("--mechanism-edge").trim(),
        line: styles.getPropertyValue("--mechanism-line").trim(),
        primary: styles.getPropertyValue("--primary-color").trim(),
        secondary: styles.getPropertyValue("--secondary-color").trim(),
        surface: styles.getPropertyValue("--surface-color").trim(),
        muted: styles.getPropertyValue("--surface-muted-color").trim(),
    };
    return paletteSnapshot;
}

function GlobeScene({ palette }: { palette: Palette }) {
    const globeRef = useRef<Group>(null);
    const reduceMotion = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    useFrame((state, delta) => {
        if (!globeRef.current || reduceMotion) return;
        globeRef.current.rotation.y += delta * 0.12;
        globeRef.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.35) * 0.08;
    });

    return (
        <group ref={globeRef}>
            <mesh scale={1.12}>
                <sphereGeometry args={[1.75, 48, 48]} />
                <meshBasicMaterial color={palette.primary} opacity={0.12} side={BackSide} transparent />
            </mesh>
            <mesh>
                <sphereGeometry args={[1.75, 64, 64]} />
                <meshStandardMaterial color={palette.surface} emissive={palette.primary} emissiveIntensity={0.025} metalness={0.08} roughness={0.82} />
            </mesh>
            <mesh scale={1.004}>
                <sphereGeometry args={[1.75, 28, 28]} />
                <meshBasicMaterial color={palette.line} transparent opacity={0.3} wireframe />
            </mesh>
            <mesh rotation={[Math.PI / 2, 0, 0]}>
                <torusGeometry args={[1.83, 0.012, 8, 64]} />
                <meshBasicMaterial color={palette.primary} transparent opacity={0.8} />
            </mesh>
            <mesh rotation={[0.65, 0.7, 0]}>
                <torusGeometry args={[1.86, 0.008, 8, 64]} />
                <meshBasicMaterial color={palette.secondary} transparent opacity={0.55} />
            </mesh>
            {ROUTES.map((route, index) => <mesh key={index}><tubeGeometry args={[route, 36, 0.012, 6, false]} /><meshBasicMaterial color={index % 2 ? palette.secondary : palette.primary} opacity={0.85} transparent /></mesh>)}
            {NODES.map((position, index) => <group key={index} position={position}><mesh><sphereGeometry args={[0.065, 16, 16]} /><meshBasicMaterial color={palette.primary} /></mesh><mesh><sphereGeometry args={[0.11, 16, 16]} /><meshBasicMaterial color={palette.secondary} opacity={0.22} transparent /></mesh></group>)}
        </group>
    );
}

export default function ForensicGlobe() {
    const palette = useSyncExternalStore(() => () => undefined, getPalette, () => null as Palette | null);

    if (!palette) return <div aria-hidden="true" className="h-full w-full animate-loading-pulse bg-(--surface-muted-color)" />;

    return <Canvas aria-label="Animated global evidence network" camera={{ fov: 40, position: [0, 0, 5.6] }} dpr={[1, 1.5]} role="img"><ambientLight color={palette.muted} intensity={2.4} /><pointLight color={palette.primary} intensity={12} position={[3, 2, 4]} /><pointLight color={palette.secondary} intensity={8} position={[-3, -2, 2]} /><GlobeScene palette={palette} /></Canvas>;
}
