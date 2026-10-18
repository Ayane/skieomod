#include "SkiEONaniteCommandlet.h"

#include "AssetCompilingManager.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Interfaces/ITargetPlatform.h"
#include "Interfaces/ITargetPlatformManagerModule.h"
#include "MeshDescription.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Rendering/NaniteResources.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "StaticMeshAttributes.h"
#include "StaticMeshResources.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "UObject/StructOnScope.h"
#include "UObject/UnrealType.h"

IMPLEMENT_MODULE(FDefaultModuleImpl, SkiEONanite);
DEFINE_LOG_CATEGORY_STATIC(LogSkiEONanite, Log, All);

USkiEONaniteCommandlet::USkiEONaniteCommandlet()
{
    IsClient = false;
    IsServer = false;
    IsEditor = true;
    LogToConsole = true;
}

namespace
{
bool ReadBuffer(const TSharedPtr<FJsonObject>& Document, const FString& Directory,
                const TCHAR* Name, int64 Bytes, TArray<uint8>& Result)
{
    const TSharedPtr<FJsonObject>* Buffers;
    const TSharedPtr<FJsonObject>* Entry;
    FString File;
    if (!Document->TryGetObjectField(TEXT("buffers"), Buffers)
        || !(*Buffers)->TryGetObjectField(Name, Entry)
        || !(*Entry)->TryGetStringField(TEXT("file"), File)
        || File != FPaths::GetCleanFilename(File)
        || !FFileHelper::LoadFileToArray(Result, *(Directory / File))
        || Result.Num() != Bytes)
    {
        UE_LOG(LogSkiEONanite, Error, TEXT("Invalid %s buffer, expected %lld bytes"), Name, Bytes);
        return false;
    }
    return true;
}

bool Finite(const FVector3f& Vector)
{
    return FMath::IsFinite(Vector.X) && FMath::IsFinite(Vector.Y) && FMath::IsFinite(Vector.Z);
}
}

int32 USkiEONaniteCommandlet::Main(const FString& Params)
{
    FString Input, ReportFile;
    if (!FParse::Value(*Params, TEXT("Input="), Input)
        || !FParse::Value(*Params, TEXT("Report="), ReportFile))
    {
        UE_LOG(LogSkiEONanite, Error, TEXT("Expected -Input=<mesh.json> -Report=<cook-report.json>"));
        return 1;
    }
    FString Text;
    TSharedPtr<FJsonObject> Document;
    if (!FFileHelper::LoadFileToString(Text, *Input)
        || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Document)
        || !Document.IsValid()) return 2;
    double Version, VerticesValue, TrianglesValue;
    FString PackageName, Coordinates, Winding;
    if (!Document->TryGetNumberField(TEXT("version"), Version) || Version != 1
        || !Document->TryGetNumberField(TEXT("vertices"), VerticesValue)
        || !Document->TryGetNumberField(TEXT("triangles"), TrianglesValue)
        || !FMath::IsFinite(VerticesValue) || !FMath::IsFinite(TrianglesValue)
        || VerticesValue < 3 || VerticesValue > 1000000 || FMath::FloorToDouble(VerticesValue) != VerticesValue
        || TrianglesValue < 1 || TrianglesValue > 2000000 || FMath::FloorToDouble(TrianglesValue) != TrianglesValue
        || !Document->TryGetStringField(TEXT("package"), PackageName)
        || !PackageName.StartsWith(TEXT("/Game/CustomMaps/")) || !FPackageName::IsValidLongPackageName(PackageName)
        || !Document->TryGetStringField(TEXT("coordinate_system"), Coordinates) || Coordinates != TEXT("east-south-up-metres")
        || !Document->TryGetStringField(TEXT("winding"), Winding) || Winding != TEXT("counterclockwise"))
    {
        UE_LOG(LogSkiEONanite, Error, TEXT("Unsupported geometry, package or vertex budget"));
        return 3;
    }
    const int32 VertexCount = static_cast<int32>(VerticesValue);
    const int32 TriangleCount = static_cast<int32>(TrianglesValue);
    const TArray<TSharedPtr<FJsonValue>>* Origin;
    if (!Document->TryGetArrayField(TEXT("origin_meters"), Origin) || Origin->Num() != 3) return 3;
    for (const auto& Value : *Origin)
    {
        double Coordinate;
        if (!Value->TryGetNumber(Coordinate) || !FMath::IsFinite(Coordinate)) return 3;
    }
    TArray<uint8> PositionData, NormalData, UVData, IndexData;
    const FString Directory = FPaths::GetPath(Input);
    if (!ReadBuffer(Document, Directory, TEXT("positions"), int64(VertexCount)*12, PositionData)
        || !ReadBuffer(Document, Directory, TEXT("normals"), int64(VertexCount)*12, NormalData)
        || !ReadBuffer(Document, Directory, TEXT("uvs"), int64(VertexCount)*8, UVData)
        || !ReadBuffer(Document, Directory, TEXT("indices"), int64(TriangleCount)*12, IndexData)) return 4;
    const auto* Positions = reinterpret_cast<const FVector3f*>(PositionData.GetData());
    const auto* Normals = reinterpret_cast<const FVector3f*>(NormalData.GetData());
    const auto* UVs = reinterpret_cast<const FVector2f*>(UVData.GetData());
    const auto* Indices = reinterpret_cast<const uint32*>(IndexData.GetData());
    for (int32 Vertex = 0; Vertex < VertexCount; ++Vertex)
    {
        if (!Finite(Positions[Vertex]) || Positions[Vertex].GetAbsMax() > 10000
            || !Finite(Normals[Vertex]) || FMath::Abs(Normals[Vertex].SizeSquared()-1) > .01f
            || !FMath::IsFinite(UVs[Vertex].X) || !FMath::IsFinite(UVs[Vertex].Y)) return 5;
    }
    for (int32 Index = 0; Index < TriangleCount*3; ++Index)
        if (Indices[Index] >= uint32(VertexCount)) return 6;

    // Require Windows cooking explicitly; a Linux fallback is incompatible with the installed game.
    ITargetPlatform* Windows = GetTargetPlatformManagerRef().FindTargetPlatform(TEXT("Windows"));
    if (!Windows)
    {
        UE_LOG(LogSkiEONanite, Error, TEXT("Windows target platform is unavailable; no asset was cooked"));
        return 7;
    }
    FMeshDescription Description;
    FStaticMeshAttributes Attributes(Description);
    Attributes.Register();
    auto VertexPositions = Attributes.GetVertexPositions();
    auto InstanceNormals = Attributes.GetVertexInstanceNormals();
    auto InstanceUVs = Attributes.GetVertexInstanceUVs();
    InstanceUVs.SetNumChannels(1);
    TArray<FVertexID> IDs;
    IDs.Reserve(VertexCount);
    for (int32 Vertex = 0; Vertex < VertexCount; ++Vertex)
    {
        FVertexID ID = Description.CreateVertex();
        IDs.Add(ID);
        VertexPositions[ID] = Positions[Vertex]*100.0f;
    }
    FPolygonGroupID Group = Description.CreatePolygonGroup();
    Attributes.GetPolygonGroupMaterialSlotNames()[Group] = TEXT("Limestone");
    for (int32 Triangle = 0; Triangle < TriangleCount; ++Triangle)
    {
        TArray<FVertexInstanceID, TInlineAllocator<3>> Instances;
        // Right-handed portable mesh to Unreal's clockwise front faces.
        for (int32 Corner : {0, 2, 1})
        {
            uint32 Index = Indices[Triangle*3+Corner];
            FVertexInstanceID ID = Description.CreateVertexInstance(IDs[Index]);
            InstanceNormals[ID] = Normals[Index];
            InstanceUVs.Set(ID, 0, UVs[Index]);
            Instances.Add(ID);
        }
        Description.CreatePolygon(Group, Instances);
    }
    UPackage* Package = CreatePackage(*PackageName);
    UStaticMesh* Mesh = NewObject<UStaticMesh>(Package, *FPackageName::GetLongPackageAssetName(PackageName), RF_Public | RF_Standalone);
    // Material is assigned from the game at runtime; no game content or new shader is embedded.
    Mesh->GetStaticMaterials().Add(FStaticMaterial(nullptr, TEXT("Limestone")));
    FMeshNaniteSettings Settings;
    Settings.bEnabled = true;
    Settings.PositionPrecision = 3; // 0.125 cm, sufficient for centimetric surface detail.
    Settings.KeepPercentTriangles = 1.0f;
    Settings.TrimRelativeError = 0.0f;
    Settings.GenerateFallback = ENaniteGenerateFallback::Enabled;
    Settings.FallbackTarget = ENaniteFallbackTarget::RelativeError;
    Settings.FallbackRelativeError = 1.0f;
    double MeshAlgorithm = 0;
    Document->TryGetNumberField(TEXT("mesh_algorithm"), MeshAlgorithm);
    if (MeshAlgorithm == 3)
    {
        // Independent fallback reductions move shared partition borders.
        // Retain the already reduced portable surface for partitioned maps.
        Settings.FallbackTarget = ENaniteFallbackTarget::PercentTriangles;
        Settings.FallbackPercentTriangles = 1.0f;
        Settings.FallbackRelativeError = 0.0f;
    }
    Mesh->SetNaniteSettings(Settings);
    UStaticMesh::FBuildMeshDescriptionsParams Build;
    Build.bFastBuild = false;
    Build.bBuildSimpleCollision = false;
    Build.bCommitMeshDescription = true;
    Mesh->SetNumSourceModels(1);
    auto& BuildSettings = Mesh->GetSourceModel(0).BuildSettings;
    BuildSettings.bRecomputeNormals = false;
    BuildSettings.bRecomputeTangents = true;
    BuildSettings.bGenerateLightmapUVs = false;
    if (!Mesh->BuildFromMeshDescriptions({&Description}, Build)) return 8;
    FAssetCompilingManager::Get().FinishAllCompilation();
    auto* Resources = Mesh->GetRenderData()->NaniteResourcesPtr.Get();
    if (!Resources || Resources->RootData.IsEmpty() || !Resources->NumClusters)
    {
        UE_LOG(LogSkiEONanite, Error, TEXT("Nanite build produced no clusters"));
        return 9;
    }
    Mesh->BeginCacheForCookedPlatformData(Windows);
    FAssetCompilingManager::Get().FinishAllCompilation();
    // This query starts the platform-specific build and asynchronous Nanite
    // bulk-data recovery. FinishAllCompilation alone does not wait for DDC IO.
    const double Deadline = FPlatformTime::Seconds()+300.0;
    while (!Mesh->IsCachedCookedPlatformDataLoaded(Windows))
    {
        if (FPlatformTime::Seconds() > Deadline)
        {
            UE_LOG(LogSkiEONanite, Error, TEXT("Windows Nanite bulk-data cache timed out"));
            return 10;
        }
        FAssetCompilingManager::Get().FinishAllCompilation();
        FPlatformProcess::Sleep(0.01f);
    }
    FStaticMeshRenderData* CookData = Mesh->GetRenderData();
    while (CookData && !CookData->SupportedPlatforms.Contains(Windows))
        CookData = CookData->NextCachedRenderData.Get();
    if (!CookData || !CookData->NaniteResourcesPtr.IsValid()
        || CookData->NaniteResourcesPtr->RootData.IsEmpty()
        || !CookData->NaniteResourcesPtr->NumClusters) return 10;
    const uint32 Clusters = CookData->NaniteResourcesPtr->NumClusters;
    const int32 RootBytes = CookData->NaniteResourcesPtr->RootData.Num();
    const int32 FallbackTriangles = CookData->LODResources.IsEmpty()
        ? 0 : CookData->LODResources[0].GetNumTriangles();

    // Epic 5.8's CookAsset uses the loose cooked package writer and bulk-data handling.
    // Invoke its reflected interface: its C++ header is private to UnrealEd.
    UClass* Cooker = FindObject<UClass>(nullptr, TEXT("/Script/UnrealEd.CookFunctionLibrary"));
    UFunction* Function = Cooker ? Cooker->FindFunctionByName(TEXT("CookAsset")) : nullptr;
    if (!Function) return 11;
    FStructOnScope Arguments(Function);
    auto* ObjectArg = FindFProperty<FObjectProperty>(Function, TEXT("Object"));
    auto* PlatformArg = FindFProperty<FStrProperty>(Function, TEXT("ForPlatform"));
    auto* DirectoryArg = FindFProperty<FStrProperty>(Function, TEXT("DestinationSubfolder"));
    auto* CommandArg = FindFProperty<FStrProperty>(Function, TEXT("CookCommandlineArgs"));
    if (!ObjectArg || !PlatformArg || !DirectoryArg || !CommandArg) return 12;
    void* Data = Arguments.GetStructMemory();
    ObjectArg->SetObjectPropertyValue_InContainer(Data, Mesh);
    PlatformArg->SetPropertyValue_InContainer(Data, TEXT("Windows"));
    DirectoryArg->SetPropertyValue_InContainer(Data, TEXT("SkiEONanite"));
    CommandArg->SetPropertyValue_InContainer(Data, TEXT(""));
    const FString Cooked = FPaths::ConvertRelativePathToFull(FPaths::ProjectSavedDir()/TEXT("Temp/SkiEONanite")/PackageName.Mid(1)+TEXT(".uasset"));
    // Prevent an old asset from being mistaken for a successful new cook.
    IFileManager::Get().Delete(*Cooked);
    Cooker->GetDefaultObject()->ProcessEvent(Function, Data);
    UPackage::WaitForAsyncFileWrites();
    if (IFileManager::Get().FileSize(*Cooked) <= 0) return 13;
    TSharedPtr<FJsonObject> Report = MakeShared<FJsonObject>();
    Report->SetBoolField(TEXT("nanite_built"), true);
    Report->SetStringField(TEXT("target_platform"), TEXT("Windows"));
    Report->SetStringField(TEXT("asset"), PackageName+TEXT(".")+FPackageName::GetLongPackageAssetName(PackageName));
    Report->SetStringField(TEXT("cooked_uasset"), Cooked);
    Report->SetNumberField(TEXT("vertices"), VertexCount);
    Report->SetNumberField(TEXT("triangles"), TriangleCount);
    Report->SetNumberField(TEXT("nanite_clusters"), Clusters);
    Report->SetNumberField(TEXT("root_bytes"), RootBytes);
    Report->SetNumberField(TEXT("fallback_triangles"), FallbackTriangles);
    Report->SetField(TEXT("origin_meters"), Document->Values[TEXT("origin_meters")]);
    Report->SetBoolField(TEXT("game_render_verified"), false);
    FString Output;
    FJsonSerializer::Serialize(Report.ToSharedRef(), TJsonWriterFactory<>::Create(&Output));
    if (!FFileHelper::SaveStringToFile(Output, *ReportFile)) return 14;
    UE_LOG(LogSkiEONanite, Display, TEXT("Built %u Nanite clusters; cooked for Windows: %s"), Clusters, *Cooked);
    return 0;
}
