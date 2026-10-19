#version 440
// Silk Studio: flowing, line-threaded curtains, convex horizon, edge lift,
// soft text-contrast veil, and a configurable vignette.
// The uniform names must match the ShaderEffect properties in Overlay.qml.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float energy;
    float danger;
    float speed;
    float heightFactor;
    float sideHeight;
    float sideWidth;
    float brightness;
    float density;
    float sharpness;
    float wave;
    float drift;
    float baseGlow;
    float edgeBoost;
    float edgeColorMix;
    float offsetX;
    float offsetY;
    float vignetteStrength;
    float vignetteRadius;
    float vignetteSoftness;
    float convexity;
    float archWidth;
    float textContrast;
    float textPadding;
    float textFeather;
    vec2 textCenter;
    vec2 textExtent;
    vec4 colorA;
    vec4 colorB;
    vec4 colorC;
    vec4 colorD;
    vec4 edgeColor;
    vec4 errorColor;
    vec4 vignetteColor;
    vec4 textContrastColor;
} u;

const float TAU = 6.28318530718;
float hash1(float n) { return fract(sin(n * 92.7 + 13.3) * 43758.5453); }
float noise1(float x) {
    float i = floor(x);
    float f = fract(x);
    f = f*f*(3.0-2.0*f);
    return mix(hash1(i), hash1(i+1.0), f);
}
float band(float x, float y, float t, float scale, float phase) {
    float warp = sin(y*4.8 + t*0.38 + phase) * 0.085;
    return 0.5 + 0.5 * sin(TAU * (x*scale + phase + warp));
}
void main() {
    vec2 uv = qt_TexCoord0;
    float y = clamp(1.0 - uv.y - u.offsetY, 0.0, 1.8);
    float x = uv.x - 0.5 - u.offsetX;
    float t = u.time * clamp(u.speed, 0.0, 6.0);
    float e = clamp(u.energy, 0.0, 1.0);
    float edgeDistance = min(uv.x, 1.0 - uv.x);
    float edge = 1.0 - smoothstep(0.0, max(0.001, u.sideWidth), edgeDistance);

    // Convex rise: center is taller while edges receive a separately limited lift.
    float centerArch = exp(-pow(x / max(0.05, u.archWidth), 2.0));
    float reachCenter = max(0.015, u.heightFactor)
                       * (0.62 + clamp(u.convexity, 0.0, 2.0)*0.57*centerArch);
    float reach = mix(reachCenter, max(0.015, u.sideHeight), edge*0.86);
    float wx = x + sin(y*3.8 + t*0.26) * u.wave * 0.9
                 + sin(y*8.0 - t*0.19 + x*7.0) * u.wave * 0.54;

    float d = clamp(u.density, 3.0, 200.0) * 0.12;
    float s = clamp(u.sharpness, 1.0, 24.0);
    float a = pow(band(wx, y, t, d*0.85, 0.22), max(1.0, s*0.19));
    float b = pow(band(wx, y, -t*0.7, d*1.3, 1.8), max(1.0, s*0.24));
    float c = pow(band(wx, y, t*0.56, d*2.15, 2.9), max(1.0, s*0.30));
    float threads = pow(max(0.0, 0.5 + 0.5 * sin(TAU*(wx*clamp(u.density,3.0,200.0)*0.72
                                                   + t*u.drift))), max(2.0, s*1.9));
    float strandRandom = 0.62 + 0.38*noise1(floor(wx*d*12.0)*0.41+2.3);

    // Soft but clearly threaded sheets. Top fades rather than ending in a hard line.
    float shape = exp(-y/max(0.018, reach*0.79));
    float top = 1.0-smoothstep(reach*0.63, reach+0.065, y);
    float curtains = (a*0.46 + b*0.29 + c*0.20 + threads*0.25*strandRandom)
                     * shape * top;
    float underside = exp(-y/max(0.010, reach*0.13))*clamp(u.baseGlow,0.0,2.0);
    float sideMist = edge*exp(-y/max(0.02,u.sideHeight*0.44))*0.13;
    float emission = (curtains+underside+sideMist)
                    * clamp(u.brightness,0.0,5.0)
                    * (0.88+e*0.40)
                    * (1.0 + edge*clamp(u.edgeBoost,0.0,3.0));

    float chroma = clamp(0.50+0.50*sin(wx*5.3-t*0.10+y*1.1), 0.0, 1.0);
    vec3 col = mix(u.colorA.rgb,u.colorB.rgb,smoothstep(0.0,0.43,chroma));
    col = mix(col,u.colorC.rgb,smoothstep(0.31,0.74,chroma)*0.72);
    col = mix(col,u.colorD.rgb,smoothstep(0.68,1.0,chroma)*0.60);
    col = mix(col,u.edgeColor.rgb,edge*clamp(u.edgeColorMix,0.0,1.0));
    col = mix(col,u.errorColor.rgb,clamp(u.danger,0.0,1.0));

    float auroraAlpha = clamp(emission*0.65,0.0,0.86);
    vec2 centered = (uv-vec2(0.5))*vec2(1.08,1.0);
    float rad = length(centered);
    float vignette = smoothstep(u.vignetteRadius,
                  u.vignetteRadius+max(0.01,u.vignetteSoftness),rad);
    float vignetteAlpha = vignette*clamp(u.vignetteStrength,0.0,0.95);

    // No opaque card. The softly feathered backdrop is centered on the actual
    // message geometry, and it darkens the aurora where legibility is needed.
    vec2 span = max(u.textExtent*0.5*(1.0+clamp(u.textPadding,0.0,2.0)),vec2(0.018));
    vec2 delta = (uv-u.textCenter)/span;
    float veil = 1.0 - smoothstep(0.66,1.0+max(0.05,u.textFeather),length(delta));
    float shadeAlpha = veil*clamp(u.textContrast,0.0,0.95);

    vec3 premul = col*auroraAlpha + u.vignetteColor.rgb*vignetteAlpha*(1.0-auroraAlpha);
    float alpha = auroraAlpha + vignetteAlpha*(1.0-auroraAlpha);
    premul = u.textContrastColor.rgb*shadeAlpha + premul*(1.0-shadeAlpha);
    alpha = shadeAlpha + alpha*(1.0-shadeAlpha);
    fragColor = vec4(premul,alpha)*u.qt_Opacity;
}
