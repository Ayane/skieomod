-- Only private bridges require offsets. Public reflected fields may move.
-- These anchors are additional checks, not proof of an arbitrary private ABI.
return {
    terrain={classes={
        ['/Script/SkiResortSimulator.TerrainHeightCacheSubsystem']={
            WindExposureTex={type='ObjectProperty',offset=0x170},
            SnowRedistributionTex={type='ObjectProperty',offset=0x198},
            CanopyTex={type='ObjectProperty',offset=0x1C0},
            PlacementSlopeTex={type='ObjectProperty',offset=0x340},
        },
        ['/Script/Landscape.LandscapeComponent']={
            SectionBaseX={type='IntProperty',offset=0x578},
            MaterialInstances={type='ArrayProperty',offset=0x5A0},
            HeightmapTexture={type='ObjectProperty',offset=0x688},
            HeightmapScaleBias={type='StructProperty',offset=0x610,
                struct={X='DoubleProperty',Y='DoubleProperty',Z='DoubleProperty',W='DoubleProperty'}},
            CachedLocalBox={type='StructProperty',offset=0x630},
        },
    }},
    session={classes={['/Script/SkiResortSimulator.GameSessionSubsystem']={
        PendingInitialSave={type='ObjectProperty',offset=0x68},
        PendingScenario={type='ObjectProperty',offset=0x70},
        OnNewGameStarted={type='MulticastInlineDelegateProperty',offset=0xB0},
    }}},
    placement={classes={['/Script/SkiResortSimulator.PlaceableActor']={
        BuildingRadius={type='FloatProperty',offset=0x300},
        bConformsToTerrain={type='BoolProperty',offset=0x318},
        TerrainSnapBufferCm={type='FloatProperty',offset=0x328},
    }}},
    ground_height={parameters={WorldContextObject='ObjectProperty',X='FloatProperty',Y='FloatProperty',ReturnValue='FloatProperty'},
        order={'WorldContextObject','X','Y','ReturnValue'}},
    terrain_height={parameters={WorldContextObject='ObjectProperty',Location='StructProperty',ReturnValue='FloatProperty'},
        order={'WorldContextObject','Location','ReturnValue'}},
}
