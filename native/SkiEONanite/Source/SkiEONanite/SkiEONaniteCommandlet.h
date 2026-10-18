#pragma once

#include "Commandlets/Commandlet.h"
#include "SkiEONaniteCommandlet.generated.h"

UCLASS()
class USkiEONaniteCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    USkiEONaniteCommandlet();
    virtual int32 Main(const FString& Params) override;
};
