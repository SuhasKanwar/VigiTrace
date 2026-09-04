"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useRef, useSyncExternalStore } from "react";
import { BackSide, type Group } from "three";

type Palette = Record<"mechanism" | "edge" | "line" | "primary" | "secondary", string>;

const NODES: [number, number, number][] = [[0.55, 0.6, 1.46], [-1.1, 0.25, 1.18], [1.1, -0.15, 1.18], [-0.25, -0.95, 1.28], [0.2, 1.05, 1.2]];
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
                <meshStandardMaterial color={palette.mechanism} emissive={palette.edge} emissiveIntensity={0.22} metalness={0.15} roughness={0.72} />
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
            {NODES.map(([x, y, z]) => <mesh key={`${x}-${y}-${z}`} position={[x, y, z]}><sphereGeometry args={[0.055, 16, 16]} /><meshBasicMaterial color={palette.primary} /></mesh>)}
        </group>
    );
}

export default function ForensicGlobe() {
    const palette = useSyncExternalStore(() => () => undefined, getPalette, () => null as Palette | null);

    if (!palette) return <div aria-hidden="true" className="h-full w-full animate-loading-pulse bg-(--mechanism-edge)" />;

    return <Canvas aria-label="Animated global evidence network" camera={{ fov: 40, position: [0, 0, 5.6] }} dpr={[1, 1.5]} role="img"><ambientLight intensity={1.3} /><pointLight color={palette.primary} intensity={20} position={[3, 2, 4]} /><pointLight color={palette.secondary} intensity={12} position={[-3, -2, 2]} /><GlobeScene palette={palette} /></Canvas>;
}
