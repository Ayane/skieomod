using UnrealBuildTool;

public class SkiEONanite : ModuleRules
{
    public SkiEONanite(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new[] {
            "Core", "CoreUObject", "Engine", "UnrealEd", "Json", "MeshDescription",
            "StaticMeshDescription", "MeshBuilder", "NaniteBuilder", "RenderCore", "RHI",
            "TargetPlatform", "WindowsTargetPlatform", "WindowsTargetPlatformSettings",
            "WindowsTargetPlatformControls"
        });
    }
}
