using UnrealBuildTool;

public class SkiEONaniteEditorTarget : TargetRules
{
    public SkiEONaniteEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        bBuildAllModules = false;
        ExtraModuleNames.Add("SkiEONanite");
        bWithLiveCoding = false;
    }
}
