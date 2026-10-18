using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;
using System.Buffers.Binary;
using System.Security.Cryptography;
using System.Text;

if (args.Length == 4 && args[0] == "extract-initial-save")
{
    var saveMappings = new Usmap(args[2]);
    var saveAsset = new UAsset(args[1], EngineVersion.VER_UE5_8, saveMappings);
    var saveExport = saveAsset.Exports
        .OfType<NormalExport>()
        .FirstOrDefault(export => export["SaveBytes"] is ArrayPropertyData);
    byte[] bytes;
    if (saveExport?["SaveBytes"] is ArrayPropertyData saveBytes &&
        saveBytes.Value.All(value => value is BytePropertyData))
    {
        bytes = saveBytes.Value
            .Cast<BytePropertyData>()
            .Select(value => value.Value)
            .ToArray();
    }
    else
    {
        // Some very large byte arrays are deliberately left as RawExport by
        // UAssetAPI's safety limit. Their cooked layout is the byte count,
        // followed immediately by the GVAS payload.
        var sidecar = Path.ChangeExtension(args[1], ".uexp");
        var exportBytes = File.ReadAllBytes(sidecar);
        var magicOffset = exportBytes.AsSpan().IndexOf("GVAS"u8);
        if (magicOffset < 4)
        {
            Console.Error.WriteLine("InitialSaveAsset.SaveBytes was not found");
            return 1;
        }

        var byteCount = BinaryPrimitives.ReadUInt32LittleEndian(
            exportBytes.AsSpan(magicOffset - 4, 4));
        if (byteCount > int.MaxValue || magicOffset + byteCount > exportBytes.Length)
        {
            Console.Error.WriteLine("Invalid InitialSaveAsset.SaveBytes length");
            return 1;
        }
        bytes = exportBytes.AsSpan(magicOffset, checked((int)byteCount)).ToArray();
    }
    if (bytes.Length < 4 || !bytes.AsSpan(0, 4).SequenceEqual("GVAS"u8))
    {
        Console.Error.WriteLine("Embedded data is not an Unreal SaveGame archive");
        return 1;
    }

    File.WriteAllBytes(args[3], bytes);
    Console.WriteLine($"Extracted {bytes.Length} SaveGame bytes to {args[3]}");
    return 0;
}

if (args.Length == 6 &&
    (args[0] == "rename-package" || args[0] == "replace-reference"))
{
    var simpleMappings = new Usmap(args[2]);
    var simpleAsset = new UAsset(args[1], EngineVersion.VER_UE5_8, simpleMappings);
    var oldPackage = args[4];
    var newPackage = args[5];
    var oldName = Path.GetFileName(oldPackage);
    var newName = Path.GetFileName(newPackage);
    var fullReplacements = 0;
    var nameReplacements = 0;

    foreach (var entry in simpleAsset.GetNameMapIndexList())
    {
        if (entry?.Value == oldPackage)
        {
            entry.Value = newPackage;
            fullReplacements++;
        }
        else if (entry?.Value == oldName)
        {
            entry.Value = newName;
            nameReplacements++;
        }
    }

    if (fullReplacements == 0 || nameReplacements == 0)
    {
        Console.Error.WriteLine(
            $"Reference not found completely: full={fullReplacements}, name={nameReplacements}");
        return 1;
    }

    if (args[0] == "rename-package")
        simpleAsset.FolderName = new FString(newPackage);

    simpleAsset.Write(args[3]);
    Console.WriteLine(
        $"{args[0]}: {oldPackage} -> {newPackage} " +
        $"({fullReplacements} full, {nameReplacements} name)");
    return 0;
}

if (args.Length == 5 && args[0] == "patch-collision")
{
    const int collisionSide = 64;
    const int collisionSamples = collisionSide * collisionSide;
    const int collisionComponentOffset = 1024;
    const int collisionExtrasSize = 12825;
    const int heightsCountOffset = 46;
    const int heightsOffset = 50;
    const int minimumOffset = 8254;
    const int maximumOffset = 8262;
    const int rowCountOffset = 8270;
    const int columnCountOffset = 8272;
    const int rangeOffset = 8274;
    const int heightPerUnitOffset = 8282;
    const int materialCountOffset = 8290;
    const int lowResolutionCountOffset = 12263;
    const int lowResolutionOffset = 12267;
    const int lowResolutionSide = 11;
    const int lowResolutionIncrement = 6;
    const int lowResolutionColumnCountOffset = 12751;
    const int localBoundsMinimumZOffset = 12809;
    const int localBoundsMaximumZOffset = 12821;

    var collisionMappings = new Usmap(args[2]);
    var collisionAsset = new UAsset(
        args[1], EngineVersion.VER_UE5_8, collisionMappings);
    var collisionHeightBytes = File.ReadAllBytes(args[4]);
    if (collisionHeightBytes.Length != 2017 * 2017 * 2)
    {
        Console.Error.WriteLine(
            $"R16 has {collisionHeightBytes.Length} bytes instead of {2017 * 2017 * 2}");
        return 2;
    }

    ushort CollisionHeightAt(int x, int y)
    {
        var offset = 2 * (y * 2017 + x);
        return BinaryPrimitives.ReadUInt16LittleEndian(
            collisionHeightBytes.AsSpan(offset, 2));
    }

    static uint ReadUInt32At(byte[] data, int offset) =>
        BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4));

    static void WriteDoubleAt(byte[] data, int offset, double value) =>
        BinaryPrimitives.WriteInt64LittleEndian(
            data.AsSpan(offset, 8), BitConverter.DoubleToInt64Bits(value));

    static void WriteFloatAt(byte[] data, int offset, float value) =>
        BinaryPrimitives.WriteInt32LittleEndian(
            data.AsSpan(offset, 4), BitConverter.SingleToInt32Bits(value));

    var patchedCollisions = 0;
    foreach (var export in collisionAsset.Exports)
    {
        var name = export.ObjectName?.ToString();
        if (export is not NormalExport normal || name is null ||
            !name.StartsWith(
                "LandscapeHeightfieldCollisionComponent_", StringComparison.Ordinal))
            continue;

        if (!int.TryParse(
                name.AsSpan("LandscapeHeightfieldCollisionComponent_".Length),
                out var exportNumber))
        {
            Console.Error.WriteLine($"Unexpected collision component name: {name}");
            return 1;
        }

        var component = exportNumber - collisionComponentOffset;
        var componentX = component % 32;
        var componentY = component / 32;
        if (component < 0 || componentX >= 32 || componentY >= 32)
        {
            Console.Error.WriteLine($"Unexpected collision component index: {name}");
            return 1;
        }

        var data = normal.Extras;
        if (data.Length != collisionExtrasSize ||
            ReadUInt32At(data, 12) != collisionExtrasSize - 16 ||
            ReadUInt32At(data, 28) != 12 ||
            ReadUInt32At(data, heightsCountOffset) != collisionSamples ||
            BinaryPrimitives.ReadUInt16LittleEndian(
                data.AsSpan(rowCountOffset, 2)) != collisionSide ||
            BinaryPrimitives.ReadUInt16LittleEndian(
                data.AsSpan(columnCountOffset, 2)) != collisionSide ||
            ReadUInt32At(data, materialCountOffset) != 63 * 63 ||
            ReadUInt32At(data, lowResolutionCountOffset) !=
                lowResolutionSide * lowResolutionSide ||
            BinaryPrimitives.ReadUInt16LittleEndian(
                data.AsSpan(lowResolutionColumnCountOffset, 2)) != lowResolutionSide)
        {
            Console.Error.WriteLine($"Unexpected Chaos heightfield layout in {name}");
            return 1;
        }

        var rawHeights = new int[collisionSamples];
        var minimum = int.MaxValue;
        var maximum = int.MinValue;
        for (var y = 0; y < collisionSide; y++)
        for (var x = 0; x < collisionSide; x++)
        {
            var raw = (int)CollisionHeightAt(
                componentX * 63 + x, componentY * 63 + y) - 32768;
            rawHeights[y * collisionSide + x] = raw;
            minimum = Math.Min(minimum, raw);
            maximum = Math.Max(maximum, raw);
        }

        var quantized = new ushort[collisionSamples];
        var range = maximum - minimum;
        for (var index = 0; index < collisionSamples; index++)
        {
            quantized[index] = range == 0
                ? (ushort)0
                : checked((ushort)(
                    (rawHeights[index] - minimum) /
                    (range / (double)ushort.MaxValue)));
            BinaryPrimitives.WriteUInt16LittleEndian(
                data.AsSpan(heightsOffset + index * 2, 2), quantized[index]);
        }

        var heightPerUnit = range == 0
            ? 0.0
            : range / (double)ushort.MaxValue;
        WriteDoubleAt(data, minimumOffset, minimum);
        WriteDoubleAt(data, maximumOffset, maximum);
        WriteDoubleAt(data, rangeOffset, range);
        WriteDoubleAt(data, heightPerUnitOffset, heightPerUnit);

        for (var lowY = 0; lowY < lowResolutionSide; lowY++)
        for (var lowX = 0; lowX < lowResolutionSide; lowX++)
        {
            var lowMinimum = ushort.MaxValue;
            var lowMaximum = ushort.MinValue;
            var firstY = lowY * lowResolutionIncrement;
            var firstX = lowX * lowResolutionIncrement;
            for (var y = firstY; y <= Math.Min(firstY + 6, 63); y++)
            for (var x = firstX; x <= Math.Min(firstX + 6, 63); x++)
            {
                var value = quantized[y * collisionSide + x];
                lowMinimum = Math.Min(lowMinimum, value);
                lowMaximum = Math.Max(lowMaximum, value);
            }

            var lowIndex = lowY * lowResolutionSide + lowX;
            BinaryPrimitives.WriteUInt16LittleEndian(
                data.AsSpan(lowResolutionOffset + lowIndex * 4, 2), lowMinimum);
            BinaryPrimitives.WriteUInt16LittleEndian(
                data.AsSpan(lowResolutionOffset + lowIndex * 4 + 2, 2), lowMaximum);
        }

        // FHeightField expands its local AABB by 1e-4 around the decoded,
        // quantized samples. Reproducing that detail matters when the extrema
        // map to 65534 because of floating-point truncation.
        var decodedMinimum = minimum + quantized.Min() * heightPerUnit;
        var decodedMaximum = minimum + quantized.Max() * heightPerUnit;
        WriteFloatAt(
            data, localBoundsMinimumZOffset, (float)(decodedMinimum - 0.0001));
        WriteFloatAt(
            data, localBoundsMaximumZOffset, (float)(decodedMaximum + 0.0001));

        var outer = (StructPropertyData)normal["CachedLocalBox"];
        var box = (BoxPropertyData)outer.Value[0];
        box.Value = new TBox<FVector>(
            new FVector(0.0, 0.0, minimum / 128.0),
            new FVector(63.0, 63.0, maximum / 128.0),
            1);

        // A copied GUID makes Chaos reuse the already-loaded source heightfield
        // even when the serialized data differs. Give each Veymont component a
        // stable identity derived from its package and row-major index.
        var guidSeed = Encoding.UTF8.GetBytes(
            $"{collisionAsset.FolderName.Value}:heightfield:{component}");
        var guidBytes = MD5.HashData(guidSeed);
        var guidOuter = (StructPropertyData)normal["HeightfieldGuid"];
        ((GuidPropertyData)guidOuter.Value[0]).Value = new Guid(guidBytes);
        patchedCollisions++;
    }

    if (patchedCollisions != 1024)
    {
        Console.Error.WriteLine(
            $"Patched {patchedCollisions} collision components instead of 1024");
        return 1;
    }

    collisionAsset.Write(args[3]);
    Console.WriteLine(
        $"Rebuilt {patchedCollisions} Chaos heightfields from the R16 terrain");
    return 0;
}

if (args.Length == 8 && args[0] == "redistribute-obstacles")
{
    const int redistributedLandscapeSide = 2017;
    const double redistributedLandscapeMinimum = -403200.0;
    const double redistributedLandscapeMaximum = 403200.0;
    const double redistributedLandscapeSpacing = 400.0;
    const double redistributedLandscapeLocationZ = 154318.75;
    const double redistributedLandscapeHeightStepCm = 2.5;
    const double redistributedPositionStepCm = 0.1;
    const double redistributedMinimumXY = -404000.0;

    var redistributedMappings = new Usmap(args[2]);
    var redistributedAsset = new UAsset(
        args[1], EngineVersion.VER_UE5_7, redistributedMappings);
    var redistributedHeightBytes = File.ReadAllBytes(args[4]);
    if (redistributedHeightBytes.Length !=
        redistributedLandscapeSide * redistributedLandscapeSide * 2)
    {
        Console.Error.WriteLine("Invalid redistribution R16 size");
        return 2;
    }

    var points = File.ReadAllBytes(args[5]);
    if (points.Length < 12 || !points.AsSpan(0, 4).SequenceEqual("SKXY"u8) ||
        BinaryPrimitives.ReadUInt32LittleEndian(points.AsSpan(4, 4)) != 1)
    {
        Console.Error.WriteLine("Invalid SKXY obstacle-position stream");
        return 2;
    }
    var pointCount = BinaryPrimitives.ReadUInt32LittleEndian(points.AsSpan(8, 4));
    if (points.Length != 12 + checked((int)pointCount * 8))
    {
        Console.Error.WriteLine("Invalid SKXY obstacle-position length");
        return 2;
    }

    var oldPackage = args[6];
    var newPackage = args[7];
    var redistributedOldObjectName = Path.GetFileName(oldPackage);
    var redistributedNewObjectName = Path.GetFileName(newPackage);
    redistributedAsset.FolderName = new FString(newPackage);
    foreach (var entry in redistributedAsset.GetNameMapIndexList())
    {
        if (entry?.Value == oldPackage) entry.Value = newPackage;
        if (entry?.Value == redistributedOldObjectName)
            entry.Value = redistributedNewObjectName;
    }

    if (redistributedAsset.Exports.Count != 1 ||
        redistributedAsset.Exports[0] is not RawExport redistributedRaw)
    {
        Console.Error.WriteLine("Expected one raw BakedObstacleDataAsset export");
        return 1;
    }
    var data = redistributedRaw.Data;
    var magicOffset = data.AsSpan().IndexOf("SKOB"u8);
    if (magicOffset < 0 || magicOffset + 48 > data.Length)
    {
        Console.Error.WriteLine("SKOB obstacle header not found");
        return 1;
    }
    uint ReadRedistributedUInt32(int offset) =>
        BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4));
    var formatVersion = ReadRedistributedUInt32(magicOffset + 4);
    var obstacleCount = ReadRedistributedUInt32(magicOffset + 8);
    var recordSize = ReadRedistributedUInt32(magicOffset + 12);
    var minimumZ = BitConverter.Int64BitsToDouble(
        BinaryPrimitives.ReadInt64LittleEndian(data.AsSpan(magicOffset + 32, 8)));
    var recordsOffset = magicOffset + 48;
    var recordsEnd = recordsOffset + checked((int)(obstacleCount * recordSize));
    if (formatVersion != 1 || recordSize != 19 || pointCount != obstacleCount ||
        recordsEnd + 12 != data.Length)
    {
        Console.Error.WriteLine(
            $"Unexpected obstacle redistribution layout: points={pointCount}, " +
            $"records={obstacleCount}, size={recordSize}");
        return 1;
    }

    static void WriteRedistributedDouble(byte[] target, int offset, double value) =>
        BinaryPrimitives.WriteInt64LittleEndian(
            target.AsSpan(offset, 8), BitConverter.DoubleToInt64Bits(value));
    WriteRedistributedDouble(data, magicOffset + 16, redistributedMinimumXY);
    WriteRedistributedDouble(data, magicOffset + 24, redistributedMinimumXY);

    ushort HeightAtRedistributed(int x, int y)
    {
        var offset = 2 * (y * redistributedLandscapeSide + x);
        return BinaryPrimitives.ReadUInt16LittleEndian(
            redistributedHeightBytes.AsSpan(offset, 2));
    }

    double SampleRedistributedHeight(double worldX, double worldY)
    {
        var sampleX = Math.Clamp(
            (worldX - redistributedLandscapeMinimum) / redistributedLandscapeSpacing,
            0.0, redistributedLandscapeSide - 1.0);
        var sampleY = Math.Clamp(
            (worldY - redistributedLandscapeMinimum) / redistributedLandscapeSpacing,
            0.0, redistributedLandscapeSide - 1.0);
        var x0 = Math.Min((int)Math.Floor(sampleX), redistributedLandscapeSide - 2);
        var y0 = Math.Min((int)Math.Floor(sampleY), redistributedLandscapeSide - 2);
        var fx = sampleX - x0;
        var fy = sampleY - y0;
        var encodedHeight =
            HeightAtRedistributed(x0, y0) * (1.0 - fx) * (1.0 - fy) +
            HeightAtRedistributed(x0 + 1, y0) * fx * (1.0 - fy) +
            HeightAtRedistributed(x0, y0 + 1) * (1.0 - fx) * fy +
            HeightAtRedistributed(x0 + 1, y0 + 1) * fx * fy;
        return redistributedLandscapeLocationZ +
            (encodedHeight - 32768.0) * redistributedLandscapeHeightStepCm;
    }

    var lowest = double.PositiveInfinity;
    var highest = double.NegativeInfinity;
    for (var obstacle = 0; obstacle < obstacleCount; obstacle++)
    {
        var pointOffset = 12 + obstacle * 8;
        var worldX = BitConverter.Int32BitsToSingle(
            BinaryPrimitives.ReadInt32LittleEndian(points.AsSpan(pointOffset, 4)));
        var worldY = BitConverter.Int32BitsToSingle(
            BinaryPrimitives.ReadInt32LittleEndian(points.AsSpan(pointOffset + 4, 4)));
        if (worldX < redistributedLandscapeMinimum ||
            worldX > redistributedLandscapeMaximum ||
            worldY < redistributedLandscapeMinimum ||
            worldY > redistributedLandscapeMaximum)
        {
            Console.Error.WriteLine($"Obstacle {obstacle} is outside the Landscape");
            return 1;
        }
        var worldZ = SampleRedistributedHeight(worldX, worldY);
        var recordOffset = recordsOffset + checked(obstacle * (int)recordSize);
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(recordOffset, 4),
            checked((uint)Math.Round(
                (worldX - redistributedMinimumXY) / redistributedPositionStepCm)));
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(recordOffset + 4, 4),
            checked((uint)Math.Round(
                (worldY - redistributedMinimumXY) / redistributedPositionStepCm)));
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(recordOffset + 8, 4),
            checked((uint)Math.Round(
                (worldZ - minimumZ) / redistributedPositionStepCm)));
        lowest = Math.Min(lowest, worldZ);
        highest = Math.Max(highest, worldZ);
    }

    if (ReadRedistributedUInt32(recordsEnd) != formatVersion ||
        ReadRedistributedUInt32(recordsEnd + 4) != obstacleCount ||
        ReadRedistributedUInt32(recordsEnd + 8) != 0)
    {
        Console.Error.WriteLine("Unexpected BakedObstacleDataAsset property trailer");
        return 1;
    }

    redistributedAsset.Write(args[3]);
    Console.WriteLine(
        $"Redistributed {obstacleCount} obstacles across Veymont forests " +
        $"({lowest / 100.0:F1}-{highest / 100.0:F1} m) and renamed package");
    return 0;
}

if (args.Length != 7 || (args[0] != "patch-map" && args[0] != "patch-obstacles"))
{
    Console.Error.WriteLine(
        "usage:\n" +
        "  UAssetPatcher extract-initial-save ASSET MAPPINGS OUTPUT\n" +
        "  UAssetPatcher patch-map ASSET MAPPINGS OUTPUT R16 OLD_PACKAGE NEW_PACKAGE\n" +
        "  UAssetPatcher patch-obstacles ASSET MAPPINGS OUTPUT R16 OLD_PACKAGE NEW_PACKAGE\n" +
        "  UAssetPatcher redistribute-obstacles ASSET MAPPINGS OUTPUT R16 SKXY OLD_PACKAGE NEW_PACKAGE\n" +
        "  UAssetPatcher patch-collision ASSET MAPPINGS OUTPUT R16\n" +
        "  UAssetPatcher rename-package ASSET MAPPINGS OUTPUT OLD_PACKAGE NEW_PACKAGE\n" +
        "  UAssetPatcher replace-reference ASSET MAPPINGS OUTPUT OLD_REFERENCE NEW_REFERENCE");
    return 2;
}

const int landscapeSide = 2017;
const int componentQuads = 63;
var heightBytes = File.ReadAllBytes(args[4]);
if (heightBytes.Length != landscapeSide * landscapeSide * 2)
{
    Console.Error.WriteLine(
        $"R16 has {heightBytes.Length} bytes instead of {landscapeSide * landscapeSide * 2}");
    return 2;
}

ushort HeightAt(int x, int y)
{
    var offset = 2 * (y * landscapeSide + x);
    return (ushort)(heightBytes[offset] | (heightBytes[offset + 1] << 8));
}

var mappings = new Usmap(args[2]);
var engineVersion = args[0] == "patch-obstacles"
    ? EngineVersion.VER_UE5_7
    : EngineVersion.VER_UE5_8;
var asset = new UAsset(args[1], engineVersion, mappings);
var oldObjectName = Path.GetFileName(args[5]);
var newObjectName = Path.GetFileName(args[6]);
var newObstaclePackage = args[0] == "patch-map"
    ? Path.GetDirectoryName(args[6])!.Replace('\\', '/') +
      "/DA_BakedObstacles_" + newObjectName
    : args[6];
var newObstacleObjectName = Path.GetFileName(newObstaclePackage);

asset.FolderName = new FString(args[6]);
foreach (var entry in asset.GetNameMapIndexList())
{
    if (entry?.Value == args[5]) entry.Value = args[6];
    if (entry?.Value == oldObjectName) entry.Value = newObjectName;
    if (entry?.Value == "/Game/Data/DA_BiomeSettings_Tahoe")
        entry.Value = "/Game/Data/DA_BiomeSettings_Alps";
    if (entry?.Value == "DA_BiomeSettings_Tahoe")
        entry.Value = "DA_BiomeSettings_Alps";
    if (entry?.Value == "/Game/Generated/DA_BakedObstacles_Map_sugar_bowl_real" ||
        entry?.Value == "/Game/Maps/Generated/DA_BakedObstacles_Map_vercors_gresse")
        entry.Value = newObstaclePackage;
    if (entry?.Value == "DA_BakedObstacles_Map_sugar_bowl_real" ||
        entry?.Value == "DA_BakedObstacles_Map_vercors_gresse")
        entry.Value = newObstacleObjectName;
}

if (args[0] == "patch-obstacles")
{
    if (asset.Exports.Count != 1 || asset.Exports[0] is not RawExport raw)
    {
        Console.Error.WriteLine("Expected one raw BakedObstacleDataAsset export");
        return 1;
    }

    var data = raw.Data;
    var magicOffset = data.AsSpan().IndexOf("SKOB"u8);
    if (magicOffset < 0 || magicOffset + 48 > data.Length)
    {
        Console.Error.WriteLine("SKOB obstacle header not found");
        return 1;
    }

    uint ReadUInt32(int offset) =>
        BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(offset, 4));
    double ReadDouble(int offset) =>
        BitConverter.Int64BitsToDouble(
            BinaryPrimitives.ReadInt64LittleEndian(data.AsSpan(offset, 8)));

    var formatVersion = ReadUInt32(magicOffset + 4);
    var obstacleCount = ReadUInt32(magicOffset + 8);
    var recordSize = ReadUInt32(magicOffset + 12);
    var minimumX = ReadDouble(magicOffset + 16);
    var minimumY = ReadDouble(magicOffset + 24);
    var minimumZ = ReadDouble(magicOffset + 32);
    var recordsOffset = magicOffset + 48;
    var recordsEnd = recordsOffset + checked((int)(obstacleCount * recordSize));

    if (formatVersion != 1 || recordSize != 19 || recordsEnd + 12 != data.Length)
    {
        Console.Error.WriteLine(
            $"Unexpected obstacle format: version={formatVersion}, count={obstacleCount}, " +
            $"recordSize={recordSize}, bytes={data.Length}");
        return 1;
    }

    // The Landscape spans [-403200, 403200] cm in X/Y with one sample every
    // 400 cm. R16 rows run from the north edge to the south edge, matching the
    // cooked Landscape component order used by this level.
    const double landscapeMinimum = -403200.0;
    const double landscapeSpacing = 400.0;
    const double landscapeLocationZ = 154318.75;
    const double landscapeHeightStepCm = 2.5; // scale Z 320 / 128
    const double obstaclePositionStepCm = 0.1;

    double SampleHeightCm(double worldX, double worldY)
    {
        var sampleX = Math.Clamp(
            (worldX - landscapeMinimum) / landscapeSpacing, 0.0, landscapeSide - 1.0);
        var sampleY = Math.Clamp(
            (worldY - landscapeMinimum) / landscapeSpacing, 0.0, landscapeSide - 1.0);
        var x0 = Math.Min((int)Math.Floor(sampleX), landscapeSide - 2);
        var y0 = Math.Min((int)Math.Floor(sampleY), landscapeSide - 2);
        var fx = sampleX - x0;
        var fy = sampleY - y0;
        var h00 = (double)HeightAt(x0, y0);
        var h10 = (double)HeightAt(x0 + 1, y0);
        var h01 = (double)HeightAt(x0, y0 + 1);
        var h11 = (double)HeightAt(x0 + 1, y0 + 1);
        var encodedHeight =
            h00 * (1.0 - fx) * (1.0 - fy) +
            h10 * fx * (1.0 - fy) +
            h01 * (1.0 - fx) * fy +
            h11 * fx * fy;
        return landscapeLocationZ + (encodedHeight - 32768.0) * landscapeHeightStepCm;
    }

    var lowest = double.PositiveInfinity;
    var highest = double.NegativeInfinity;
    for (var obstacle = 0; obstacle < obstacleCount; obstacle++)
    {
        var recordOffset = recordsOffset + checked((int)(obstacle * recordSize));
        var quantizedX = ReadUInt32(recordOffset);
        var quantizedY = ReadUInt32(recordOffset + 4);
        var worldX = minimumX + quantizedX * obstaclePositionStepCm;
        var worldY = minimumY + quantizedY * obstaclePositionStepCm;
        var heightCm = SampleHeightCm(worldX, worldY);
        var quantizedZ = checked((uint)Math.Round(
            (heightCm - minimumZ) / obstaclePositionStepCm));
        BinaryPrimitives.WriteUInt32LittleEndian(
            data.AsSpan(recordOffset + 8, 4), quantizedZ);
        lowest = Math.Min(lowest, heightCm);
        highest = Math.Max(highest, heightCm);
    }

    // FormatVersion, ObstacleCount and the UObject terminator follow RawData.
    if (ReadUInt32(recordsEnd) != formatVersion ||
        ReadUInt32(recordsEnd + 4) != obstacleCount ||
        ReadUInt32(recordsEnd + 8) != 0)
    {
        Console.Error.WriteLine("Unexpected BakedObstacleDataAsset property trailer");
        return 1;
    }

    asset.Write(args[3]);
    Console.WriteLine(
        $"Grounded {obstacleCount} obstacles on Veymont terrain " +
        $"({lowest / 100.0:F1}-{highest / 100.0:F1} m) and renamed package");
    return 0;
}

static void SetVector(NormalExport export, string property, FVector value)
{
    var outer = (StructPropertyData)export[property];
    ((VectorPropertyData)outer.Value[0]).Value = value;
}

var componentCount = 0;
foreach (var export in asset.Exports)
{
    var name = export.ObjectName?.ToString();
    if (export is not NormalExport normal || name is null) continue;

    if (name == "RootComponent0")
    {
        SetVector(normal, "RelativeLocation", new FVector(-403200.0, -403200.0, 154318.75));
        SetVector(normal, "RelativeScale3D", new FVector(400.0, 400.0, 320.0));
    }
    else if (name == "LevelEnvironmentSettings_1")
    {
        ((FloatPropertyData)normal["PeakElevationMeters"]).Value = 2341.10693359375f;
        ((FloatPropertyData)normal["BaseElevationMeters"]).Value = 745.26806640625f;
        SetVector(normal, "PreviewCameraLocation",
            new FVector(-680000.0, -680000.0, 470000.0));
    }
    else if (name.StartsWith("LandscapeComponent_", StringComparison.Ordinal) &&
             int.TryParse(name.AsSpan("LandscapeComponent_".Length), out var component))
    {
        var componentX = component % 32;
        var componentY = component / 32;
        if (componentY >= 32) continue;

        var min = ushort.MaxValue;
        var max = ushort.MinValue;
        for (var y = componentY * componentQuads;
             y <= (componentY + 1) * componentQuads; y++)
        for (var x = componentX * componentQuads;
             x <= (componentX + 1) * componentQuads; x++)
        {
            var height = HeightAt(x, y);
            if (height < min) min = height;
            if (height > max) max = height;
        }

        var outer = (StructPropertyData)normal["CachedLocalBox"];
        var box = (BoxPropertyData)outer.Value[0];
        box.Value = new TBox<FVector>(
            new FVector(0.0, 0.0, (min - 32768.0) / 128.0),
            new FVector(63.0, 63.0, (max - 32768.0) / 128.0),
            1);
        componentCount++;
    }
}

if (componentCount != 1024)
{
    Console.Error.WriteLine($"Patched {componentCount} Landscape components instead of 1024");
    return 1;
}

asset.Write(args[3]);
Console.WriteLine(
    $"Patched package, Alps biome, transform, elevations, camera and {componentCount} bounds");
return 0;
