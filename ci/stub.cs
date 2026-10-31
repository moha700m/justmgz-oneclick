using System;
using System.IO;

class Stub
{
    static int Main(string[] args)
    {
        string exe = Path.GetFileNameWithoutExtension(Environment.GetCommandLineArgs()[0]).ToLowerInvariant();
        string s = string.Join(" ", args);

        if (exe == "wsl")
        {
            if (s.Contains("wslpath")) { Console.WriteLine("/mnt/c/actions/justmgz-oneclick"); return 0; }
            if (s.Contains("cat /tmp/justmgz-apt.rc")) { Console.WriteLine("0"); return 0; }
            if (s.Trim() == "-u root -e true") return 0;
            Console.WriteLine("[stub] wsl " + s);
            return 0;
        }
        if (exe == "usbipd" && args.Length > 0 && args[0] == "list")
        {
            Console.WriteLine("BUSID  VID:PID    DEVICE                        STATE");
            Console.WriteLine("3-1    05ac:12a8  Apple Inc. iPhone             Not shared");
            return 0;
        }
        Console.WriteLine("[stub] " + exe + " " + s);
        return 0;
    }
}
